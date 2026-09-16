# Publish Gas Weather

## Prepared deployment

This is a Python Streamlit app. Streamlit Community Cloud can run it on a remote
server and assign a public `streamlit.app` URL. The deployed app works independently
of the owner's Mac. A public app can be opened by anyone with its link.

The project is prepared for Python **3.12**, with the tested package versions in
`requirements.txt`. Current ecCodes Python packages supply the Linux binary
dependency; no `packages.txt` is needed. The required Census CSV is included.

Build the clean upload folder and ZIP from the project directory:

```bash
.venv/bin/python scripts/package_deployment.py
```

The script writes `.runtime/deployment/gas-weather/` and
`.runtime/deployment/gas-weather.zip`. It includes application source, tests,
documentation, and the public Census CSV. It excludes secrets, installed packages,
local logs, downloaded caches, and the local database. The ZIP contains the
repository files at its root; extract it before uploading to GitHub.

## Account step and deployment

1. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub.
   Account setup may ask you to accept its terms and authorize GitHub access.
2. Create a GitHub repository for the prepared files. A private repository keeps
   the source private; the deployed app's audience is configured separately.
3. In Community Cloud, choose **Create app → Yup, I have an app**.
4. Choose that repository, its actual branch, and **app.py** as the entrypoint.
   Set **Python 3.12** in the advanced settings. No API secrets are required.
5. Deploy and set the app's audience to public so Dad can open the URL without
   an account. Check the deployed page, all four NOAA images, and the source audit.

No repository or public app has been created by preparing the upload folder.
Record the actual repository and deployed URL here once deployment succeeds.

## Hosted behavior

- A first launch downloads the current public sources and available recent GFS
  archives. This can take longer than reopening a warm app.
- Concurrent visitors share server-side weather data; their navigation and
  adjustable demand assumptions are separate browser-session settings.
- The host's local database and cache may reset after a restart or redeploy.
  This V1 rebuilds available recent forecast comparisons from NOAA; it does not
  provide durable long-term cloud storage.
- Community Cloud may put inactive apps to sleep. A visitor can wake a sleeping
  app; free hosting is not a guarantee of uninterrupted availability.
- Sources are checked when a session opens or when Update the data is pressed.
  Leaving the page open does not start a scheduled refresh.

References: [Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud),
[deployment steps](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[app dependencies](https://docs.streamlit.io/deploy/concepts/dependencies),
[ECMWF ecCodes Python](https://github.com/ecmwf/eccodes-python).
