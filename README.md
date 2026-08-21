# inreach - v0.1.4

A set of python tools designed to speed up scripting in Halo Reach.

System Requirements:
- Windows
- Steam version of Halo Master Chief Collection Installed
- Halo Reach Multiplayer Installed
- Tesseract OCR Installed*


## Install

### Make sure Tesseract OCR is installed and on PATH:
Tesseract Optical Character Recognition is used for some in-game Menu manipulation. You can either install it before hand (and add it to PATH) or let the install process handle it.*

### Setup virtual environment and install inreach
- `cd` to desired location, then setup virtual env with python 3.14+ and activate
- install inreach via pip: `pip install inreach`
- (optional) verify system installs before creating a project `inreach verify`

## Usage

To run the new project wizard run the following without arguments:

```
inreach init
```

Follow the on-screen instructions to setup a new project from either:
- a blank variant:
    - either Multiplayer or Firefight
- standard variants:
    - (game and hopper game variants)






Alternatively run with arguments to...

```
inreach init --arg1 "val" --arg2 "val"
```
-- fill with args 

Or load a "project.rch.json" directly:

Verify the status of 