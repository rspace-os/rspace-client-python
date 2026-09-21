# Design record: the unified PyFilesystem (`rspace_client.fs`)

Tracked in GitHub #58. Everything here is built. The document records the decisions behind the
shape of the package, several of which were reversed during the build and would otherwise be
re-argued. For what the filesystem does today, read [`usage-guide.md`](usage-guide.md); this is
about why it is shaped that way and what must not move.

## 1. Shape

One `MountFS` with three branches, sharing one `ELNClient` and one `InventoryClient`:

```
RSpaceFilesystem(server, api_key)
    /gallery     GalleryFilesystem      GF folders are directories, GL files are files
    /inventory   InventoryFilesystem    benches and the sections Containers, Samples, Templates;
                                        every record is a folder holding child records and attachments
    /workspace   WorkspaceFilesystem    Home folder tree; a document is a folder of its text fields,
                                        a field is a folder of the files linked into it
```

`mounts=` narrows the set. The top level is fixed and cannot be written to. The alternative,
one monolithic `FS` dispatching on global-ID prefix, would re-implement what `MountFS` already
does and still have to solve the root listing. Each branch stays small and testable on its own.

**One consistency rule across all branches.** A directory is anything that contains files (a
Gallery folder, an Inventory record, an ELN folder, notebook or document); a file is a
downloadable blob (a `GL` Gallery file, an `IF` Inventory attachment, a media file linked into
a document). Every `Info` carries the raw RSpace record under the `rspace` namespace.

**Shared base** (`fs/base.py`): the write posture, the path style, one `Target` and one segment
walker, one Info builder, the `scandir` served from a single listing call, lazy page streaming,
the error translation and the folder and download templates. A branch supplies only its own
vocabulary: how a path resolves, what a directory contains, where a file's bytes come from.

## 2. Paths

Three spellings of a segment, chosen by `path_style`: `name` (`microscope.png`, the default),
`labelled` (`microscope.png [GL100]`), `id` (`GL100`). A segment carrying a global ID resolves
under every style; a bare name resolves only under `name`, by one listing of its parent, cached
per instance and cleared on every write through the filesystem.

Why `name` is the default, given the two alternatives:

- *Bare IDs* (`GF123`) are what the deprecated classes used. Galaxy shows `info.name`, so
  users saw global IDs instead of the names they gave their records.
- *Labelled segments* (`microscope.png [GL100]`) keep both. But PyFilesystem defines
  `info.name` as the path segment and Galaxy derives both the label it shows and the path it
  addresses from that one field, so the ID travelled into downloaded file names and swallowed
  the extension, and Galaxy picks a dataset type from the extension.
- *Names* raise objections that turn out to be answerable. Slashes and backslashes are replaced, NULs
  dropped, whitespace collapsed. A name that reduces to `.` or `..` is listed by its ID.
  Siblings sharing a name are disambiguated as the listing streams, without lookahead: the
  first keeps the name, later ones carry their ID before the extension (`data [GL112].csv`).
  A name that would itself parse as an address (`GL9`, `report [GL111].csv`) is listed with
  its real ID appended the same way, so a listed segment always opens the record it shows.
  Renames do break a stored `name` path; `labelled` and `id` exist for callers that need a
  path to survive one.

Inventory adds fixed section names at its root, so each branch has a real resolver rather than
the old "strip the two-letter prefix" helper. Nothing in a path is a page token: `page-N`
pseudo-folders were built and removed, see section 5.

## 3. Write posture

Read-only by default. `writable=True` allows uploads, folder creation and links;
`allow_delete=True` allows removals. The two are separate on purpose, so `getmeta()["read_only"]`
is false if either is set. Every mutating method is marked with `@writes` or `@deletes` in the
base, and the mount wraps its in-memory root in `read_only` so a write to the top level cannot
silently succeed. A `move` checks the delete permission before copying anything.

`remove` deliberately differs per branch: in the Workspace it unlinks the file from its field
and leaves the Gallery file alone; in the Inventory it deletes the attachment record; in the
Gallery it is unsupported, because the API cannot delete Gallery files. Each says which it did.

A signed ELN document is locked. Every field write (upload, link, remove) refuses before any
request is made, and a document's fields are listed with a `(signed)` suffix under the `name`
style and report the lock in the `access` namespace. The folder-tree endpoint does not carry
the flag, so the document's own entry in its parent listing is not marked.

Uploading into a text field is a read-modify-write of the field's HTML; concurrent edits are
last-writer-wins, as they are for the web client.

## 4. What each branch contains

**Gallery.** Root resolved lazily on first use from the Home tree (no network in a
constructor). The folder-tree endpoint returns no file sizes, so a listing that asks for the
`details` namespace, as Galaxy does, fetches each file's record to fill `size` in; a `basic`
listing stays at one call. Upload routing: the Gallery is split into media-type
sections and a file may only go into a folder of the matching section; `upload` returns a
`Placement`, and a mismatch either raises `GallerySectionMismatch` or, with
`on_mismatch="reroute"`, lets RSpace file it and reports where it landed.

**Inventory.** Root lists benches (read via `/workbenches/{id}`, since `/containers/{id}`
answers 422 for a bench) and the sections. A container lists its child containers and
subsamples plus attachments; a sample lists its subsamples plus attachments; a subsample lists
its attachments plus a `sample: <name>` shortcut folder holding the sample's attachments only,
so the tree has no cycles. Samples are not stored in containers, their subsamples are.

Records carry files in two disjoint places: their own `attachments`, and template-defined
attachment fields (`SF`) on samples, templates and instruments, each holding at most one file.
Only `attachment`-type fields are shown, as folders of 0 or 1 file. Uploading into an occupied
field is refused with `DestinationExists` rather than replacing, because a folder reads as
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
legacy `Attachment` type is uncreatable and always empty. The document's Info counts the
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
branch serves `scandir` from one listing call rather than one `getinfo` per child, and fills
`details.size/created/modified` as epoch seconds for consumers that read them. `info.name` is
always the entry's own segment, never the full path (the old Inventory class reported the full path, a bug found
with the mock harness).

Section and folder listings are lazy streams that follow the API's `next` links only as far
as the consumer reads. `page_size` is the fetch batch size, default 100, invisible in the
namespace. This replaced `page-N` pseudo-folders after seeing them in Galaxy's file browser,
where they read as data rather than as an implementation detail; Galaxy paginates natively
through `filterdir(page=(start, end))`, so page folders had it paginating over our pagination.

## 6. Errors

RSpace client exceptions are translated once, at every public method of the base class: a
404 becomes `ResourceNotFound`, 401 and 403 `PermissionDenied`, a 5xx or lost connection
`RemoteConnectionError`. This is what makes `exists()`, `walk()` and `copy()` behave.
Statuses with a domain meaning (400, 409, 422: a refused link, a wrong Gallery section) stay
as `ApiError` so the server's own explanation reaches the caller.

## 7. Opener

`fs.open_fs("rspace://host")` returns an `RSpaceFilesystem`. The URL carries the host and
options only. The key is read from `RSPACE_API_KEY` and nothing else: a URL is often supplied
by someone other than the person whose environment it is opened in, so it must not be able to
name the variable that leaves the machine. User info in the URL is refused. Plain http is
accepted for loopback hosts only. The client never follows a redirect, because requests keeps
the `apiKey` header across a change of host.

## 8. Galaxy, the load-bearing consumer

Galaxy pins `rspace-client>=2.6.1,<3` and ships a file source (`galaxy/files/sources/rspace.py`,
since Galaxy 25.1) that **subclasses the deprecated** `rspace_client.eln.fs.GalleryFilesystem`
and monkeypatches `ELNClient.upload_file` with a function taking only
`(file, folder_id, caption)`. It relies on four things no documented API promises:

| Galaxy relies on | Kept by |
| --- | --- |
| `upload_file` accepting no extra keyword | the shims send no `filename=`; only the new classes do |
| `upload(folder_path, file)` naming the file after the file object | the shims' `upload` |
| bare global-ID segments, from which it builds URIs | the shims default to `path_style="id"` |
| `basic.name`, `rspace.name`, ISO `rspace.created`, integer `size` | `make_info`, and the Gallery `details` top-up |

All four are pinned by `rspace_client/tests/galaxy_plugin_contract_test.py`, which copies
Galaxy's wrapper classes so the suite runs without Galaxy installed. **A failure there is a
release blocker, not a test to update.** The two shims (`rspace_client.eln.fs`,
`rspace_client.inv.attachment_fs`, plus `rspace_client.inv.fs` for the import documented in
issue #57) default to `writable=True, allow_delete=True, path_style="id"`, keep the
folder-as-path upload convention and the historical multipart body, and warn on construction.
They cannot be removed on a schedule: removal follows a Galaxy release that no longer imports
them, no earlier than 3.0.

Galaxy discovers file sources by walking its own package, so exposing `/inventory` and
`/workspace` to Galaxy users needs a pull request to `galaxyproject/galaxy`: a new
`rspace_unified` source built on `RSpaceFilesystem`, and optionally pointing the existing
source at `rspace_client.fs.GalleryFilesystem` with `path_style="id"` so saved URIs survive. That pull request depends on a released
`rspace-client` that contains this package.
