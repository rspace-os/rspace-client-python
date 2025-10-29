markdown syntax (for jupyter markdown cells)
https://www.markdownguide.org/basic-syntax/#line-break-best-practices
========
Keyring (library we use to store password)
https://pypi.org/project/keyring/10.0.2/
======
Installing dependencies if not using magics (magics are code that starts with '%' - syntactic sugar around calls to IPython)
https://jakevdp.github.io/blog/2017/12/05/installing-python-packages-from-jupyter/

===========
Kernels:
https://github.com/jupyter/jupyter/wiki/Jupyter-kernels
========
https://cran.r-project.org/web/packages/reticulate/vignettes/calling_python.html#:~:text=Overview,%24listdir(%22.%22)
=====
Reticulate: https://rstudio.github.io/reticulate/index.html

Calling python from R

install.packages('reticulate')
library('reticulate')
library("future")
plan(multisession)
py_require(c('pickleshare'))
py_require(c('notebook'))
py_require(c('keyring'))
py_require(c('rspace_client==2.6.2'))
py_require(c('dill'))
py_require(c('ipynbname'))
py_require(c('ipylab'))
py_require(c('lxml'))
py_require(c('keyrings.alt'))
py_require(c('bs4'))
py_require(c('nbformat'))
py_require(c('keyring'))
asyncio <- import("asyncio") 
sync_notebook <- import('rspace_client.notebook_sync.sync_notebook')
(You will see an error message: 
name 'get_ipython' is not definedTraceback:
All references to get_ipython need to be removed from the sync_notebook code - which then breaks it for python. In the end it was not possible to package a non python version with poetry so I stopped trying to have R Cells call python.
However, technically it does work).
run:

asyncio$run(sync_notebook$sync_notebook_to_rspace(rspace_username="user1a",attached_data_files="spectroscopy_data.csv",rspace_url="https://researchspace2.eu.ngrok.io/", notebook_name="R4_D4.ipynb", server_url="localhost:10111"))
=====
Docker STACKS
Im running the script docker stack locally. I used: 

docker run -p 10000:8888 quay.io/jupyter/scipy-notebook:latest
python -c "import sys; print('\n',sys.version); import ipympl; print('ipympl version:', ipympl.__version__)" && jupyter --version && jupyter labextension list

And for the datascience Jupyter stack:
docker run -it --rm -p 10111:8888 -v "${PWD}":/home/jovyan/work quay.io/jupyter/datascience-notebook:2025-03-14

======
BeautifulSoup for removing html tags
https://www.crummy.com/software/BeautifulSoup/bs4/doc/
=======
IPYLAB
**Install of Ipylab requires a browser refresh after %pip install step or it does not work and SAVE FAILS**

Note JupyterLab lists all commands here: https://jupyterlab.readthedocs.io/en/latest/user/commands.html - ipylab can call these commands through its proxy.

app.commands.execute('docmanager:save') - does save the notebook! (Asynchronous)

Using JupyterFrontEnd from ipylab 
https://nbviewer.org/github/jtpio/ipylab/blob/main/examples/commands.ipynb
Ready event

Listing Commands are asynchronous 
Some functionalities might require the JupyterFrontEnd widget to be ready on the frontend first.
This is for example the case when listing all the available commands, or retrieving the version with app.version.
The on_ready method can be used to register a callback that will be fired when the frontend is ready.
(In https://github.com/jtpio/ipylab/blob/main/examples/commands.ipynb)

IPYLAB: https://github.com/jtpio/ipylab
=======

TIPS and Tricks
https://www.dataquest.io/blog/jupyter-notebook-tips-tricks-shortcuts/

===========
ASYNCIO

https://docs.python.org/3/library/asyncio-task.html
======

MAGICS:

https://ipython.readthedocs.io/en/stable/interactive/magics.html#

==========
NBGITPULLER https://github.com/jupyterhub/nbgitpuller (The Bonn Jupyter expert said that this could be used to have Jupyter 'pull' data from RSPace and that we would not be able to push data
from RSpace to Jupyter (at least at Bonnm who use multiple K8 clusters and each user ends up with a dedicated K8 node))

=====

NBFORMAT: https://nbformat.readthedocs.io/en/latest/format_description.html - used to read and write notebooks

Kaggle https://www.kaggle.com/code/neilhanlon/notebook8ec06231db/edit username is Rspace email

Parent:
https://researchspace.atlassian.net/jira/polaris/projects/RPD/ideas/view/3486269?selectedIssue=RPD-65

NBViewer https://nbviewer.org/ for publishing notebooks. We cant claim that there is not an existing mechanism to make notebooks public as this actually does it.

Docker stacks https://jupyter-docker-stacks.readthedocs.io/en/latest/index.html
Link to base notebook image on BINDER: try the quay.io/jupyter/base-notebook image 

Open Notebooks in R: https://tmphub.elff.eu/ (think its a BINDER Session)

Log in to a Jupyter hub discussion: https://discourse.jupyter.org/t/jupyterhub-api-only-mode-how-should-user-login-work/36278

IPYTHON : https://ipython.readthedocs.io/en/stable/config/extensions/storemagic.html

JupyterLite https://jupyterlite.readthedocs.io/en/latest/howto/pyodide/packages.html

Binder tutorial on Jupyter https://hub.gesis.mybinder.org/user/ipython-ipython-in-depth-a351eg8t/notebooks/binder/Index.ipynb

https://jupyterlab.readthedocs.io/en/latest/user/extensions.html EXTENSIONS that are browser based and are found on window._JUPYTER

https://github.com/timkpaine/jupyterlab_commands install commands

Forum https://discourse.jupyter.org/t/how-to-avoid-multiple-kernels-per-notebook/11645

JUPYTERLAB demo on binder : https://hub.2i2c.mybinder.org/user/jupyterlab-jupyterlab-demo-j2k4tj7o/lab/tree/demo

JUPYTERLAB docs https://jupyterlab.readthedocs.io/en/latest/user/export.html

JUPYTER HUB REST API https://jupyterhub.readthedocs.io/en/5.2.1/reference/rest-api.html uses oauth. 

https://jupyterhub.readthedocs.io/en/latest/howto/rest.html 
See especially The same API token can also authorize access to the Jupyter Notebook REST API
provided by notebook servers managed by JupyterHub if it has the necessary access:servers scope.

JUPYTER SERVER REST API https://jupyter-server.readthedocs.io/en/latest/developers/rest-api.html

https://github.com/jupyter/jupyter/wiki/Jupyter-Notebook-Server-API

https://discourse.jupyter.org/t/how-to-version-control-jupyter-notebooks/566 How to Version Control Jupyter Notebooks

How to store variables data for later runs: https://stackoverflow.com/questions/34342155/how-to-pickle-or-store-jupyter-ipython-notebook-session-for-later?rq=4

How to execute a cell remotely: https://discourse.jupyter.org/t/rest-api-for-executing-cells-in-a-notebook/21346

https://jupyter-client.readthedocs.io/en/latest/messaging.html

Server API swagger: https://petstore.swagger.io/?url=https://raw.githubusercontent.com/jupyter/jupyter_server/master/jupyter_server/services/api/api.yaml#/

How to render in React https://victordibia.com/blog/jupyter-notebooks-react/

Sandbox viewer https://codesandbox.io/p/sandbox/react-example-react-jupyter-notebook-viewer-forked-xqdmh1?file=%2Fsrc%2FApp.js

Lab archives integration https://help.labarchives.com/hc/en-us/articles/11780569021972-Jupyter-Integration

Elabftw discuss using Jupyter light. GitHubhttps://github.comJupyterLite · elabftw elabftw · Discussion #3930

ElabFTW allow display of Notebook and then revert the code due to security concerns: https://github.com/elabftw/elabftw/issues/310

THE Big SPLIT https://blog.jupyter.org/the-big-split-9d7b88a031a7

Jupyter Lite v full discussed here: https://discourse.jupyter.org/t/writing-jupyter-notebooks/24453/2 (and links to deployments)

Google Collab https://colab.research.google.com/#scrollTo=-Rh3-Vt9Nev9 uses the drive api https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get which uses oauth. But also has own api: see here for discussion and links https://stackoverflow.com/questions/50595831/google-colab-api

Provenance git projects that are installable Jupyter extensions:
https://github.com/Sheeba-Samuel/ProvBook
https://github.com/fusion-jena/MLProvLab

How to see modules: help("modules")
