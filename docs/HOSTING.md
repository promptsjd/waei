# Hosting WAIE

Reviewed against GitHub documentation on 2026-11-21. No public demo is deployed.

| Option | Runs the current editor? | Visitor experience |
| --- | --- | --- |
| GitHub Pages | No | Static information, instructions and download links |
| GitHub Codespaces | Yes, after container/model setup | GitHub sign-in, personal instance, wait for setup, open forwarded port |
| Separate application backend | Requires additional work | Could offer a public link without GitHub sign-in |

[GitHub Pages does not support server-side Python](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).
Copying the HTML to Pages leaves uploads, analysis, project saving and rendering
without their backend. Moving processing into the browser would be a separate
implementation, not a Pages configuration change.

## Personal browser trial

After publishing the source, open
[the Codespaces creation link](https://codespaces.new/promptsjd/waei).
The included `.devcontainer/` configuration installs Python 3.11, FFmpeg,
OpenCV's system libraries, CPU PyTorch, the web/vision dependencies, and both
models. It creates `.venv`, starts WAIE, and forwards port 8080. Open that port
from **Ports**, then select **Talking-head editor** or visit `/editor`.

The configuration is prepared but has not been built in an actual Codespace.
Initial setup needs internet and several minutes. It requests at least 8 GB RAM
and 32 GB storage; larger videos may need more. Start with short trial clips.

Keep port visibility **Private**, GitHub's default. Every tester should create
their own codespace. WAIE has no user login or project ownership; making a
forwarded port public shares its project library and deletion controls with
visitors. See [GitHub's port-forwarding documentation](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).

[Codespaces quotas and possible charges apply](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces).
Videos are uploaded to your codespace rather than processed on your computer.
Stop the codespace from GitHub when finished. Download exports before deleting
it; deletion removes its stored clips, models and projects.

If setup fails, retry `python tools/codespace.py setup`, then
`python tools/codespace.py start` from its terminal. Logs are in
`output/codespace-server.log`. The starter reuses a matching WAIE server and
reports a conflict rather than stopping another service on port 8080. After
source changes, stop and restart the codespace to load the new server.

## A public editor without GitHub sign-in

The current app needs a Python process, FFmpeg, CPU inference and writable
storage. A container/VM host could supply these, with GitHub holding source and
running checks. That is separate from GitHub Pages.

Before offering a shared public service, add separate user sessions and project
ownership, upload/processing limits, data cleanup/retention, and an appropriate
job/storage backend. This would process recordings on your server. Select
capacity after measuring real clips. No provider or paid plan is configured.

If GitHub sign-in is acceptable, personal Codespaces instances are the included
trial route. A public, app-only experience is a further product change.
