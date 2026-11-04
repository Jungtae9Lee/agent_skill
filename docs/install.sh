#!/usr/bin/env bash
set -euo pipefail

target="opencode"
project=""
skills=()

usage() {
  echo "usage: install.sh [--target opencode|claude|cursor] [--project DIR] SKILL..." >&2
  echo "skills: confidence discernment-nudge doc-coauthoring skill-creator" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --target) target="${2:-}"; shift 2 ;;
    --project) project="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) skills+=("$1"); shift ;;
  esac
done

[ ${#skills[@]} -gt 0 ] || usage

for skill in "${skills[@]}"; do
  case "$skill" in
    confidence|discernment-nudge|doc-coauthoring|skill-creator) ;;
    *) echo "Unknown skill: $skill" >&2; usage ;;
  esac
done

if [ -n "$project" ]; then
  dest="$(cd "$project" && pwd)/.opencode/skills"
else
  case "$target" in
    opencode) dest="$HOME/.config/opencode/skills" ;;
    claude) dest="$HOME/.claude/skills" ;;
    cursor) dest="$HOME/.cursor/skills" ;;
    *) echo "Unknown target: $target" >&2; usage ;;
  esac
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fetch_repo() {
  local owner="$1" name="$2" ref="$3"
  mkdir -p "$work/$name"
  curl -fsSL "https://codeload.github.com/$owner/$name/tar.gz/refs/heads/$ref" | tar -xz -C "$work/$name" --strip-components=1
}

fetch_repo Jungtae9Lee agent_skill main
anthropic_ready=0
mkdir -p "$dest"

for skill in "${skills[@]}"; do
  if [ "$skill" = "doc-coauthoring" ]; then
    if [ "$anthropic_ready" -eq 0 ]; then
      fetch_repo anthropics skills main
      anthropic_ready=1
    fi
    source="$work/skills/skills/doc-coauthoring"
  else
    source="$work/agent_skill/$skill"
  fi
  if [ ! -f "$source/SKILL.md" ]; then
    echo "[fail] $skill : SKILL.md not found"
    continue
  fi
  action="installed"
  if [ -e "$dest/$skill" ]; then
    rm -rf "$dest/$skill"
    action="replaced"
  fi
  cp -R "$source" "$dest/$skill"
  find "$dest/$skill" -type d -name __pycache__ -prune -exec rm -rf {} +
  echo "[$action] $skill -> $dest/$skill"
done

echo
echo "Done. Restart OpenCode, Claude Code, or Cursor if it is already running."
