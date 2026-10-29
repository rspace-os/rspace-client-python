# Design record: the RSpace fsspec filesystem (`rspace_client.fs`)

Tracked in GitHub #58 and RSDEV-1519. Everything here is built. The document records the
decisions behind the shape of the package, several of which were reversed during the build and
would otherwise be re-argued. For what the filesystem does today, read
[`usage-guide.md`](usage-guide.md); this is about why it is shaped that way and what must not
move.

The browsing model was first built on PyFilesystem2 (closed pull requests #62 to #64, branch
`fs-stack/3-unified-filesystem`) and moved to [fsspec](https://filesystem-spec.readthedocs.io/)
in October 2026: PyFilesystem2 has had no release since 2022, and Galaxy, the main consumer, is
migrating every file source to fsspec (galaxyproject/galaxy#21832). The model survived the move
unchanged; only the glue around it (mounting, errors, the opener) is fsspec's.

## 1. Shape

One fsspec filesystem with three branches, sharing one `ELNClient` and one `InventoryClient`:

```
RSpaceFilesystem(server, api_key)
    /gallery     GalleryFilesystem      GF folders are directories, GL files are files
    /inventory   InventoryFilesystem    benches and the sections Containers, Samples, Templates;
                                        every record is a folder holding child records and attachments
    /workspace   WorkspaceFilesystem    Home folder tree; a document is a folder of its text fields,
                                        a field is a folder of the files linked into it
```

`mounts=` narrows the set. The top level is fixed and cannot be written to. fsspec has no
mount filesystem, so `RSpaceFilesystem` is a small dispatcher: the first path segment names a
branch and every method is handed to that branch with the rest of the path. The alternative,
one monolithic filesystem dispatching on global-ID prefix, would still have to solve the root
listing, and each branch stays small and testable on its own this way.

**One consistency rule across all branches.** A directory is anything that contains files (a
Gallery folder, an Inventory record, an ELN folder, notebook or document); a file is a
downloadable blob (a `GL` Gallery file, an `IF` Inventory attachment, a media file linked into
a document). Every entry dict carries the raw RSpace record under the `rspace` key.

**Shared base** (`fs/base.py`): the write posture, the path style, one `Target` and one segment
walker, one entry builder, the `ls`/`scandir` served from a single listing call, lazy page
streaming, buffered reads and writes, the error translation and the folder and download
templates. A branch supplies only its own
vocabulary: how a path resolves, what a directory contains, where a file's bytes come from.

## 2. Paths

Three spellings of a segment, chosen by `path_style`: `name` (`microscope.png`, the default),
`labelled` (`microscope.png [GL100]`), `id` (`GL100`). A segment carrying a global ID resolves
under every style; a bare name resolves only under `name`, by one listing of its parent, cached
per instance and cleared on every write through the filesystem.

Why `name` is the default, given the two alternatives:

- *Bare IDs* (`GF123`) are what the deprecated classes used. Galaxy shows the segment, so
  users saw global IDs instead of the names they gave their records.
- *Labelled segments* (`microscope.png [GL100]`) keep both. But Galaxy derives both the label
  it shows and the path it addresses from the one segment, so the ID travelled into downloaded file names and swallowed
  the extension, and Galaxy picks a dataset type from the extension.
- *Names* raise objections that turn out to be answerable. Slashes and backslashes are replaced, NULs
  dropped, whitespace collapsed. A name that reduces to `.` or `..` is listed by its ID.
  Siblings sharing a name are disambiguated as the listing streams, without lookahead: the
  first keeps the name, later ones carry their ID before the extension (`data [GL112].csv`).
  A name that would itself parse as an address (`GL9`, `report [GL111].csv`) is listed with
  its real ID appended the same way, so a listed segment always opens the record it shows.
  Renames do break a stored `name` path; `labelled` and `id` exist for callers that need a
  path to survive one.

  These two listing rules are not only for people who type paths. Galaxy never resolves a
  clicked row directly: the click stores the URI string, and `realize_to` re-resolves that
  string later in a separate request (the upload job, a re-run, a workflow input). The listed
  segment *is* the stored URI, so it must parse to the record it showed, every time. Confirmed
  2026-10-06 against Galaxy 25.1 with a file genuinely named `report [GL111].txt`.

  Galaxy's search escapes `[` as `\[` and hands the pattern to `glob`; fsspec's glob translation
  ignores the escape, so a query containing a bracket matches nothing. The base class
  therefore overrides `glob` for the `<dir>/*<query>*` shape: one listing of the directory, an
  unescaped case-insensitive substring match on the last segment, results in listing order.

Inventory adds fixed section names at its root, so each branch has a real resolver rather than
the old "strip the two-letter prefix" helper. Nothing in a path is a page token: `page-N`
pseudo-folders were built and removed, see section 5.

## 3. Write posture

Read-only by default. `writable=True` allows uploads, folder creation and links;
`allow_delete=True` allows removals. The two are separate on purpose, so `read_only` is false
if either is set. Every mutating method checks the posture before any request and raises
`ReadOnlyError` (a `PermissionError`), and the fixed top level of `RSpaceFilesystem` refuses
writes the same way, so a write there cannot silently succeed. A `move` checks the delete permission before copying anything.

`remove` deliberately differs per branch: in the Workspace it unlinks the file from its field
and leaves the Gallery file alone; in the Inventory it deletes the attachment record; in the
Gallery it is unsupported, because the API cannot delete Gallery files. Each says which it did.

A signed ELN document is locked. Every field write (upload, link, remove) refuses before any
request is made, and a document's fields are listed with a `(signed)` suffix under the `name`
style and report the lock as `writable: false` in their entry. The folder-tree endpoint does not carry
the flag, so the document's own entry in its parent listing is not marked.

Uploading into a text field is a read-modify-write of the field's HTML; concurrent edits are
last-writer-wins, as they are for the web client.

## 4. What each branch contains

**Gallery.** Root resolved lazily on first use from the Home tree (no network in a
constructor). The folder-tree endpoint returns no file sizes, and Galaxy requires an integer
`size`, so with `fetch_sizes=True` (the default) a listing fetches each file's record to fill
it in; `fetch_sizes=False` keeps a listing at one call. Under PyFilesystem this was decided per
call by the requested namespace; fsspec's `ls` carries no such hint, so it is per instance.
Upload routing: the Gallery is split into media-type sections and a file may only go into
a folder of the matching section; `upload_fileobj` returns a `Placement`, and a mismatch either raises `GallerySectionMismatch` or, with
`on_mismatch="reroute"`, lets RSpace file it and reports where it landed.

**Inventory.** Root lists benches (read via `/workbenches/{id}`, since `/containers/{id}`
answers 422 for a bench) and the sections. A container lists its child containers and
subsamples plus attachments; a sample lists its subsamples plus attachments; a subsample lists
its attachments plus a `sample: <name>` shortcut folder holding the sample's attachments only,
so the tree has no cycles. Samples are not stored in containers, their subsamples are.

Records carry files in two disjoint places: their own `attachments`, and template-defined
attachment fields (`SF`) on samples, templates and instruments, each holding at most one file.
Only `attachment`-type fields are shown, as folders of 0 or 1 file. Uploading into an occupied
field is refused with `FileExistsError` rather than replacing, because a folder reads as
something you add to. Subsamples have attachments but no fields (84 live ones checked).

Where a file can go, verified live against RSpace 2.27 and refused client-side before any
upload where the server would refuse:

| Record | Own attachments | Attachment fields |
| --- | --- | --- |
| Sample | read and write | read and write where the template defines one |
| Subsample, container | read and write | none exist |
| Instrument | read and write | where the template defines one |
| Sample template | server refuses | browsable |
| Bench | server refuses | none exist |

An uploaded attachment becomes a **Gallery file** linked to the record, which is what the web
interface's "link from Gallery" produces. The alternative the API offers creates a file that
exists only inside Inventory and is reusable nowhere; `via_gallery=False` keeps it, and the
deprecated `InventoryAttachmentFilesystem` is pinned to it. Linking is also what a copy within
RSpace means: `RSpaceFilesystem.copy` from any Gallery-backed source into an Inventory record
or an ELN field calls the link endpoint instead of downloading and re-uploading, which used to
leave a permanent duplicate behind.

**Workspace.** The Home tree with the Gallery root and the Templates system
folder hidden. A document exposes its fields as sub-folders, using the field's own name; the
server's `ApiDocumentField` already supplies each field's linked `files`, so no HTML parsing is
needed to list them. Only `text` fields are shown: the form editor offers no other type that
holds files, every caller of `Field.addMediaFileLink` in rspace-web passes a text field, and the
legacy `Attachment` type is uncreatable and always empty. The document's entry counts the
omitted fields in `rspace.hiddenFields`. Uploading puts the bytes in the Gallery and appends a
`<fileId=N>` token to that field; the server rewrites the token into an `attachmentDiv` or an
`<img>` on save, and unlinking strips exactly those forms with BeautifulSoup so a field id is
never mistaken for a file id. `makedir` creates folders only. Only the user's own Home tree is
reachable; shared and group documents are not in it.

The same Gallery file can appear at several paths: under `/gallery` and under every
field it is linked into. The namespace is a set of overlapping views, not a tree of uniquely
located files.

## 5. Listings and pagination

Every RSpace listing call already returns `name`, `globalId` and timestamps per child, so each
branch serves `ls` and `scandir` from one listing call rather than one `info` per child, and
fills `size`, `created` and `mtime` as epoch seconds. Entries follow fsspec's convention:
`name` is the full path without a leading slash. The base class implements `ls` itself rather
than relying on fsspec's `_ls_from_cache` and default `info`, which return a directory's own
entry among its children and fall back to listing a path to describe it. fsspec's listings
cache is off by default and cleared on every write.

Section and folder listings are lazy streams that follow the API's `next` links only as far
as the consumer reads. `page_size` is the fetch batch size, default 100, invisible in the
namespace. This replaced `page-N` pseudo-folders after seeing them in Galaxy's file browser,
where they read as data rather than as an implementation detail, and Galaxy paginates
listings itself (after a full `ls`), so page folders had it paginating over our pagination.

## 6. Errors

RSpace client exceptions are translated once, at every public method of the base class (and
of every subclass, which `__init_subclass__` wraps), into builtin `OSError` subclasses, which
is what fsspec's own `exists`, `walk` and `copy`, and Galaxy, understand: a 404 becomes
`FileNotFoundError`, 401 and 403 `PermissionError`, a lost connection or a 502 to 504
`ConnectionError`. Every other API refusal, a 500 with a message included, becomes
`RemoteApiError`, an `OSError` that keeps the server's explanation in its message and the
original exception as `api_error`. `GallerySectionMismatch` passes through as it is, since its
message already says what to do.

## 7. Opener

`fsspec.filesystem("rspace", server=...)` and `rspace://host/...` URLs (`fsspec.open`,
`UPath`) return an `RSpaceFilesystem`, through an `fsspec.specs` entry point, so nothing has to
be imported first. The URL carries the host and options only. The key is read from
`RSPACE_API_KEY` and nothing else: a URL is often supplied by someone other than the person
whose environment it is opened in, so it must not be able to name the variable that leaves the
machine. User info in the URL is refused. Plain http is accepted for loopback hosts only. The
client never follows a redirect, because requests keeps the `apiKey` header across a change of
host.

## 8. Galaxy, the load-bearing consumer

Galaxy pins `rspace-client>=2.6.1,<3` and ships a file source (`galaxy/files/sources/rspace.py`,
since Galaxy 25.1) that **subclasses the deprecated** `rspace_client.eln.fs.GalleryFilesystem`,
monkeypatches `ELNClient.upload_file` with a function taking only `(file, folder_id, caption)`,
and passes it a `FakedNameIO` wrapper that forwards `read` through `__getattr__`. It relies on
five things no documented API promises:

| Galaxy relies on | Kept by |
| --- | --- |
| `upload_file` accepting no extra keyword | the shim sends no `filename=`; only `rspace_client.fs` does |
| `upload(folder_path, file)` naming the file after the file object | the shim's `upload`, unchanged |
| bare global-ID segments, from which it builds URIs | the shim, unchanged |
| `basic.name`, `rspace.name`, ISO `rspace.created`, integer `size` | the shim's `getinfo`, unchanged |
| a file part that only forwards `read` being accepted | `_post_multipart` wraps it, see below |

The last row is new with requests 2.34 (pinned by Galaxy 26.1): requests now checks that a
multipart file part defines `read` on its class, which `FakedNameIO` does not, so Galaxy's
export to RSpace fails with a `TypeError` whatever rspace-client is installed. The client now
wraps such an object in one that defines `read`, which fixes the shipped plugin from the
client side.

All five are pinned by `rspace_client/tests/galaxy_plugin_contract_test.py`, which copies
Galaxy's wrapper classes so the suite runs without Galaxy installed. **A failure there is a
release blocker, not a test to update.** The shims (`rspace_client.eln.fs`, which Galaxy
imports, and `rspace_client.inv.attachment_fs`, which it does not but 2.x users may) are the
2.7 PyFilesystem classes, with their section-routing helpers now imported
from `rspace_client.fs.gallery` and a `DeprecationWarning` on construction. They cannot be
removed on a schedule: removal follows a Galaxy release that no longer imports them, no
earlier than 3.0, together with the `fs` dependency and the `setuptools` pin.

Galaxy discovers file sources by walking its own package, so exposing `/inventory` and
`/workspace` to Galaxy users needs a pull request to `galaxyproject/galaxy`:
`tools/galaxy/rspace_fsspec_source.py` is the proposed file source, built on Galaxy's
`FsspecFilesSource`. It also needs a file source template type, since Galaxy's template catalog
rejects unknown types, and a raised `rspace-client` pin. Pointing the existing `rspace` type at
it with `mounts=gallery` and `path_style="id"` would keep saved URIs working and retire the
deprecated import. That pull request depends on a released `rspace-client` that contains this
package.
