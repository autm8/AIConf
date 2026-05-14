


## Build instructions.
### Build for WINDOWS:
    pyinstaller --onefile --add-data "templates\*.sh;templates" openClaw.py

### Build for OSX:
    `pyinstaller --onefile --add-data "templates\:templates" openClaw.py`
     --add-data text_files\*.txt : text_files




### Create Virtual environment
`python -m venv .venv`

### Install dependencies
`pip install -r requirements.txt`

### Run deployment
`python openClawLocal.py`

### Open OpenClaw Web Portal
`http://localhost:2026`