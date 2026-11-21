# Changelog

Application releases use semantic versioning. AI response schemas are versioned
separately for compatibility.

## Unreleased

- Keep sentences intact across pauses/fillers and request an AI script before
  selecting cuts; verify the script against selected words before rendering.
- Allow saved projects to upgrade segmentation from cached word timestamps.
- Disable clip uploads until the first Save draft succeeds.
- Use the shared editor palette for project deletion actions.
- Make Send feedback a footer text link with an email/copy dialog fallback.
- Refresh setup/workflow documentation, prepare clean source exports, and add
  an optional private Codespaces trial configuration (live validation pending).
- Simplify editor setup: automatic scene descriptions and speech-language
  detection, with recording order preserved and no analysis option controls.
- Rename the application to WAIE across the interface, metadata, feedback, docs,
  and Windows launchers.
- Obtain engine redistribution permission before the first public release.
- Link the Repo footer action to `https://github.com/promptsjd/waei`.

## 0.1.0 — initial release candidate

- WAIE branding, browser titles, app metadata, and local launchers.
- Multi-clip projects with explicit first save and later autosave.
- Local speech timestamps, optional captions, and manual AI handover.
- Validated edit plans, linked audio/video rendering, preview and download.
- Scene Scribe scene detection, storyboards, shot lists, and CLI tools.
- Persistent feedback action and repository link.
- Contributor docs, Windows/Linux CI, source exports, and versioned packaging.

This describes prepared source, not a completed public release or license grant.
