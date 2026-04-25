# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A public git repo for an Alfred workflow. The workflow itself lives in `./workflow/`, which is **symlinked into Alfred's preferences directory** at:

```
~/Library/Application Support/Alfred/Alfred.alfredpreferences/workflows/user.workflow.<UUID>
```

Because of the symlink, any edit to `workflow/info.plist` or `workflow/scripts/` is immediately live in Alfred for the maintainer — no build, no install, no deploy step for local iteration. Distribution to others is a separate flow (see "Releasing" below). Be deliberate about edits.

`prefs.plist` (workflow runtime state written by Alfred) is gitignored.

## Validate after edits

```bash
plutil -lint workflow/info.plist
python3 -m py_compile workflow/scripts/*.py
```

Smoke-test the script filter without going through Alfred:

```bash
cd workflow
python3 scripts/ts.py ""          # device list
python3 scripts/ts.py "exit"      # exit-node sublist
python3 scripts/ts.py "exit lpi"  # filtered sublist
```

The output is the JSON Alfred consumes — pipe through `python3 -m json.tool` to read.

## Architecture

Action routing — the part that requires reading multiple files to grasp:

1. **`workflow/scripts/ts.py`** is the script filter. Every item it emits carries an `action` workflow variable (`COPY`, `OPEN_URL`, `SSH`, `TOGGLE`, `SET_EXIT_NODE`) and a payload in `arg`.
2. Alfred's **Conditional utility** in `workflow/info.plist` (uid `885024D2-…`) branches on `{var:action}` and routes to the matching native Alfred object: Copy to Clipboard, Open URL, or Terminal Command.
3. Anything not matched (currently `TOGGLE` and `SET_EXIT_NODE`) falls through the **else** branch into `workflow/scripts/dispatcher.py`. The dispatcher reads `action` from the env and the target from `sys.argv[1]` (the item's `arg`, passed as `"$1"`). Its stdout becomes the body of a Post Notification.

To add a new action: emit it from `ts.py` with a unique `action` value, then either add a Conditional branch wired to a native object, or handle it in `dispatcher.py`'s `ACTIONS` dict.

**`workflow/scripts/ts_common.py`** is shared by both scripts: locates the Tailscale CLI (probes `/Applications/Tailscale.app/Contents/MacOS/Tailscale`, `/usr/local/bin/tailscale`, `/opt/homebrew/bin/tailscale`), runs it, parses `tailscale status --json` into `Device` dataclasses, and turns CLI errors into user-facing `(title, subtitle)` pairs via `classify_error`.

## Conventions and gotchas

- **Mullvad filtering.** `Device.is_mullvad` (any device tagged `tag:mullvad-exit-node`) is filtered out of the main list AND the exit-node sublist. But "is any exit node currently active?" must be computed from the **unfiltered** device list — otherwise a user routing through Mullvad sees "None ✓" incorrectly. See `main()` in `ts.py`.
- **`tailscale set --exit-node=<arg>` requires an IP or unique short node name** — not the full MagicDNS name. Pass `device.ipv4` (with `device.name` as fallback). An empty string clears the exit node.
- **Two READMEs to keep in sync.** The repo's top-level `README.md` (rendered on GitHub) and the `readme` key inside `workflow/info.plist` (the in-Alfred description) carry the same prose. Update both. Note the image paths differ: the GitHub README uses `workflow/images/...` and `workflow/icon.png`; the in-Alfred copy uses bare `images/...` and `icon.png` because Alfred renders it relative to the workflow dir.
- **User-configurable keyword.** The script filter's `keyword` field is `{var:keyword}`. The default lives in the top-level `<key>variables</key>` block in `info.plist`; the user-overridable definition lives in `userconfigurationconfig`. If you add another configurable knob, mirror that pattern.
- **No `mkdir`/install steps in code.** Per Alfred Gallery rules: no auto-updaters, no `pip install`/`brew install`, no downloading binaries. The workflow shells out to the user's already-installed Tailscale CLI only.

## Releasing

Releases are cut by tagging. `.github/workflows/release.yml` runs the [`svenko99/alfred-build-action`](https://github.com/svenko99/alfred-build-action) on `v*` tag pushes, builds a `.alfredworkflow` from `workflow/`, and attaches it to a new GitHub Release with auto-generated notes.

- **Versioning is CalVer** (`<year>.<n>`), stored in `workflow/info.plist` under the top-level `<key>version</key>`. Example: `2026.1`, `2026.2`.
- **Tag must match plist version with a `v` prefix.** The workflow has a guard step that fails the run if `${GITHUB_REF_NAME#v}` ≠ the `version` output from the build action.
- **Use annotated tags, not lightweight ones.** The repo expects `push.followTags` workflow, which only pushes annotated tags. One-time setup: `git config --global push.followTags true`.
- **Cutting a release:**
  1. Bump `version` in `workflow/info.plist` (e.g. `2026.1` → `2026.2`).
  2. `git commit -am "Release v2026.2"`
  3. `git tag -a v2026.2 -m "v2026.2"`
  4. `git push` — with `push.followTags` set, this pushes the commit *and* the annotated tag, triggering the Action. Without that config, use `git push --atomic origin main v2026.2` so the commit and tag land together.
  5. The new release appears at <https://github.com/svenko99/alfred-tailscale/releases>.
- **Patching a published release:** prefer bumping to the next CalVer (e.g. `2026.1.1` or `2026.2`) rather than rewriting the tag — anyone who already downloaded the old asset would otherwise be left with stale code.
- **`prefs.plist` is excluded** from the build by the action itself, and from the repo by `.gitignore`. Do not commit it.

## Submission constraints (Alfred Gallery)

Relevant when changing UX or metadata — see <https://alfred.app/submit/> and <https://alfred.app/submit/styleguide/>:

- Icons ≥ 256×256 (current icons are 512×512).
- Keywords "in general" ≥ 3 chars; should be user-configurable. Default `ts` is intentionally short — it is configurable, which satisfies the spirit of the rule.
- README starts with `## Usage` and uses the phrasing "via the `<keyword>` keyword". Modifier rows use `<kbd>` tags.
