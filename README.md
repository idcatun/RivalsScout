# Rivals Scout

A scouting tool for Marvel Rivals that pulls player stats — rank, peak rank, and recent hero performance — from a variety of sources.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### By in-game name

```bash
./main.py Infectious kirakeera
```

### From a NECC match

1. Go to <https://necc.leagueos.gg/> and open the match page
2. Press F12 to open developer tools
   - **Firefox:** Storage → Cookies → `https://necc.leagueos.gg/`
   - **Chromium:** Application → Cookies → `https://necc.leagueos.gg/`
3. Copy the value of the `los.sid` cookie
4. Add `LOS_SID=<value>` to a `.env` file in this directory

```bash
./main.py https://necc.leagueos.gg/match/6s6qeeauuxgslgca50o698l4c
# or
./main.py https://necc.v1.leagueos.gg/league/matches/6s6qeeauuxgslgca50o698l4c
```

### From a PCL match

1. Go to <https://esports.pcl.gg/> and open the match page
2. Press F12 to open developer tools
   - **Firefox:** Storage → Local Storage → `https://esports.pcl.gg`
   - **Chromium:** Application → Local Storage → `https://esports.pcl.gg`
3. Copy the value of `token` (starts with `eyJhb`)
4. Add `PCL_TOKEN=<value>` to a `.env` file in this directory

```bash
./main.py https://esports.pcl.gg/matches/3f50d98f-41bb-495a-b40f-087bf2f5ad8e
```

### From a screenshot

```bash
# From a saved file
./main.py path/to/screenshot.png

# From clipboard
./main.py
```

### Creating a shareable link

Add `share` before any other arguments to upload the result to jsbin and open it in your browser.

```bash
./main.py share Infectious kirakeera
./main.py share https://necc.leagueos.gg/match/6s6qeeauuxgslgca50o698l4c
```
