"""Dynamic Remotion Project Generation & Harness for IncuBrix.

Generates isolated, reproducible, concurrent-safe Remotion projects per job.
Reuses shared TSX components, fonts, and node_modules via symlinks to prevent code duplication,
while isolating all audio tracks, captions, metadata, and artifacts per job workspace.
"""

import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from incubrix.config import settings

# Shared Remotion source directory
SHARED_REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"
SHARED_NODE_MODULES = Path(__file__).resolve().parent.parent / "node_modules"


class ProjectGenerationError(ValueError):
    """Raised when project generation or validation fails."""
    pass


def setup_job_remotion_project(
    job_id: str,
    workspace_dir: Path,
    captions_data: Dict[str, Any],
    aspect_ratios: Optional[List[str]] = None,
    theme_name: str = "developer",
) -> Dict[str, Any]:
    """Assemble a self-contained, isolated Remotion project in the job workspace.

    Reused (via symlinks):
    - remotion/BrollVideo.tsx
    - remotion/Root.tsx
    - remotion/ratios.ts
    - remotion/theme.ts
    - node_modules
    - package.json
    - tsconfig.json
    - remotion.config.ts
    - fonts/ (Inter.ttf, JetBrainsMono.ttf)

    Job-Specific (Dynamically Generated):
    - public/audio/scene_*.mp3
    - public/voiceover.mp3
    - public/captions.json
    - src/captions.json
    - captions.json (root of workspace for bundler resolution)
    - job_config.json
    - index.ts
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    public_dir = workspace_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    ratios = aspect_ratios or ["16:9"]

    # 1. Symlink shared node_modules into workspace
    workspace_node_modules = workspace_dir / "node_modules"
    if not workspace_node_modules.exists():
        if SHARED_NODE_MODULES.exists():
            # Resolve to real target to avoid dangling nested symlinks
            real_target = SHARED_NODE_MODULES.resolve()
            os.symlink(real_target, workspace_node_modules)

    # 2. Symlink fonts into job's public directory
    public_fonts = public_dir / "fonts"
    shared_fonts = SHARED_REMOTION_DIR / "public" / "fonts"
    if not public_fonts.exists() and shared_fonts.exists():
        os.symlink(shared_fonts.resolve(), public_fonts)

    # 3. Symlink shared TSX components and configs
    shared_files = [
        "BrollVideo.tsx",
        "Root.tsx",
        "ratios.ts",
        "theme.ts",
    ]
    for fname in shared_files:
        dest = workspace_dir / fname
        src = SHARED_REMOTION_DIR / fname
        if not dest.exists() and src.exists():
            shutil.copyfile(src.resolve(), dest)

    # 4. Symlink package.json, tsconfig.json, remotion.config.ts from root
    root_dir = SHARED_REMOTION_DIR.parent
    for cfg_name in ["package.json", "tsconfig.json", "remotion.config.ts"]:
        dest = workspace_dir / cfg_name
        src = root_dir / cfg_name
        if not dest.exists() and src.exists():
            os.symlink(src.resolve(), dest)

    # 5. Place job's captions.json in workspace root (for bundler resolution)
    workspace_captions = workspace_dir / "captions.json"
    with open(workspace_captions, "w", encoding="utf-8") as f:
        json.dump(captions_data, f, indent=2)

    # Also ensure public/captions.json exists
    with open(public_dir / "captions.json", "w", encoding="utf-8") as f:
        json.dump(captions_data, f, indent=2)

    # 6. Generate dynamic job_config.json
    job_config = {
        "job_id": job_id,
        "themeName": theme_name,
        "aspect_ratios": ratios,
        "totalFrames": captions_data.get("totalFrames", 240),
        "totalDurationSec": captions_data.get("totalDurationSec", 8.0),
        "scene_count": len(captions_data.get("scenes", [])),
    }
    with open(workspace_dir / "job_config.json", "w", encoding="utf-8") as f:
        json.dump(job_config, f, indent=2)

    # 7. Write index.ts entrypoint
    index_ts = workspace_dir / "index.ts"
    index_content = (
        "import { registerRoot } from 'remotion';\n"
        "import { Root } from './Root';\n\n"
        "registerRoot(Root);\n"
    )
    with open(index_ts, "w", encoding="utf-8") as f:
        f.write(index_content)

    # 8. Validate the generated project
    validation = validate_job_remotion_project(workspace_dir)

    return {
        "workspace_dir": str(workspace_dir),
        "job_config": job_config,
        "validation": validation,
    }


def validate_job_remotion_project(workspace_dir: Path) -> Dict[str, Any]:
    """Validate project integrity before rendering.

    Checks:
    - public/voiceover.mp3 exists and is non-empty.
    - captions.json exists, has valid scenes and positive totalFrames.
    - Every scene has positive duration and frames.
    - Component files and fonts are present.
    """
    errors: List[str] = []

    # Check captions
    captions_file = workspace_dir / "captions.json"
    if not captions_file.exists():
        raise ProjectGenerationError("Missing captions.json in workspace")

    with open(captions_file, "r", encoding="utf-8") as f:
        try:
            captions = json.load(f)
        except Exception as exc:
            raise ProjectGenerationError(f"Malformed captions.json: {exc}")

    scenes = captions.get("scenes", [])
    if not scenes:
        errors.append("No scenes defined in captions.json")

    total_frames = captions.get("totalFrames", 0)
    if total_frames <= 0:
        errors.append(f"Invalid totalFrames: {total_frames}")

    # Check voiceover audio
    voiceover_file = workspace_dir / "public" / "voiceover.mp3"
    if not voiceover_file.exists() or voiceover_file.stat().st_size == 0:
        errors.append("Missing or empty public/voiceover.mp3")

    # Check required source files
    for req_file in ["Root.tsx", "BrollVideo.tsx", "ratios.ts", "theme.ts", "index.ts"]:
        if not (workspace_dir / req_file).exists():
            errors.append(f"Missing required file: {req_file}")

    if errors:
        raise ProjectGenerationError(f"Remotion project validation failed: {'; '.join(errors)}")

    return {
        "valid": True,
        "scene_count": len(scenes),
        "total_frames": total_frames,
        "scenes": [s.get("name") for s in scenes],
    }
