# Git Commit

## Commit Command

```bash
git add static/index.html
git commit -m "fix(auth): restore missing init and showAuth functions, add storage sync, and direct Google OAuth redirect

- Restore missing init() and showAuth() definitions in static/index.html resolving ReferenceError
- Enable instant transition to studioView upon selecting account via Google OAuth callback
- Add window storage event listener to synchronize authentication across open browser tabs
- Add direct 1-click Google Sign-in action link eliminating blank tab detachment
- All tests passing"
```

---

## Commit Details

* **Type:** `fix`
* **Scope:** `auth`
* **Title:** `restore missing init and showAuth functions, add storage sync, and direct Google OAuth redirect`
* **Files Included:**
  * `static/index.html`: Restored `init()`, `showAuth()`, added `window.addEventListener('storage')`, and direct Google OAuth link
  * `github/commits.md`: Single commit tracking file
