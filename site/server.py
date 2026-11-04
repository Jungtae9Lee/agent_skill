#!/usr/bin/env python3
"""Local page that copies skills into OpenCode, Claude Code, and Cursor."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = Path(__file__).resolve().parent
INDEX_PATH = SITE_DIR / "index.html"

PREFERRED_ORDER = (
    "confidence",
    "discernment-nudge",
    "doc-coauthoring",
    "skill-creator",
)

BLURBS = {
    "confidence": "답변의 핵심 주장과 최종 답에 확신도 P(Y)를 붙이고, 기록으로 보정 상태를 측정합니다.",
    "discernment-nudge": "조언, 추정, 분석 답변 뒤에 사실과 가정, 빠진 맥락을 점검하는 후속 질문 2~3개를 붙입니다.",
    "doc-coauthoring": "제안서, 기술 스펙, 의사결정 문서를 단계별로 함께 작성합니다.",
    "skill-creator": "스킬을 만들고 고친 뒤, eval로 성능을 측정합니다.",
}

SOURCES = {
    "confidence": "자체 제작",
    "discernment-nudge": "Anthropic",
    "doc-coauthoring": "Anthropic",
    "skill-creator": "Anthropic",
}

REMOTE_SKILLS = {
    "doc-coauthoring": {
        "repo": "anthropics/skills",
        "path": "skills/doc-coauthoring",
        "ref": "main",
    }
}

GLOBAL_TARGETS = (
    ("opencode", "OpenCode", (".config", "opencode", "skills"), "모든 프로젝트에서 OpenCode가 읽습니다."),
    ("claude", "Claude Code", (".claude", "skills"), "모든 프로젝트에서 Claude Code가 읽습니다. OpenCode도 이 폴더를 읽습니다."),
    ("cursor", "Cursor", (".cursor", "skills"), "모든 프로젝트에서 Cursor가 읽습니다."),
)

PROJECT_TARGETS = (
    ("opencode-project", "OpenCode", ".opencode", "skills"),
    ("claude-project", "Claude Code", ".claude", "skills"),
    ("cursor-project", "Cursor", ".cursor", "skills"),
)

SKIP_NAMES = {".git", "__pycache__", ".cache"}
INSTALL_LOCK = threading.Lock()


class InstallError(Exception):
    pass


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def home_dir() -> Path:
    override = os.environ.get("SKILL_INSTALL_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home()


def global_root(parts: tuple[str, ...]) -> Path:
    root = home_dir()
    for part in parts:
        root = root / part.strip()
    return root


def collapse(text: str) -> str:
    return " ".join(text.split())


def frontmatter_description(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    captured: list[str] = []
    capturing = False
    for line in text[3:end].splitlines():
        if not capturing:
            if not line.startswith("description:"):
                continue
            rest = line[len("description:") :].strip()
            if rest in {">", "|", ">-", "|-", ">+", "|+"}:
                capturing = True
                continue
            if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in {"'", '"'}:
                return rest[1:-1]
            return rest
        if line.startswith((" ", "\t")) or line.strip() == "":
            captured.append(line.strip())
            continue
        break
    return " ".join(part for part in captured if part)


def skill_blurb(skill_id: str, skill_md: Path | None) -> str:
    if skill_id in BLURBS:
        return BLURBS[skill_id]
    if skill_md and skill_md.is_file():
        try:
            description = collapse(frontmatter_description(skill_md.read_text(encoding="utf-8")))
        except OSError:
            description = ""
        if description:
            return description[:280]
    return "이 저장소의 스킬입니다."


def count_files(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_NAMES.intersection(path.parts):
            continue
        if path.suffix == ".pyc":
            continue
        total += 1
    return total


def discover_skills() -> list[dict]:
    found: dict[str, dict] = {}
    for child in REPO_ROOT.iterdir():
        if not child.is_dir() or child.name.startswith(".") or child.name == "site":
            continue
        skill_md = child / "SKILL.md"
        remote = REMOTE_SKILLS.get(child.name)
        if skill_md.is_file():
            found[child.name] = {
                "id": child.name,
                "name": child.name,
                "blurb": skill_blurb(child.name, skill_md),
                "source": SOURCES.get(child.name, "이 저장소"),
                "remote": False,
                "files": count_files(child),
            }
        elif remote is not None:
            found[child.name] = {
                "id": child.name,
                "name": child.name,
                "blurb": skill_blurb(child.name, None),
                "source": SOURCES.get(child.name, "이 저장소"),
                "remote": True,
                "files": None,
            }
    ordered = [found[name] for name in PREFERRED_ORDER if name in found]
    ordered.extend(found[name] for name in sorted(found) if name not in PREFERRED_ORDER)
    return ordered


def project_dir(raw: str) -> Path | None:
    text = (raw or "").strip().strip('"')
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise InstallError("프로젝트 경로는 전체 경로로 입력해 주세요.")
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise InstallError("프로젝트 경로를 확인하지 못했습니다.") from exc
    if not resolved.exists() or not resolved.is_dir():
        raise InstallError("프로젝트 폴더를 찾지 못했습니다.")
    return resolved


def target_catalog(project: Path | None) -> list[dict]:
    targets = []
    for target_id, label, parts, detail in GLOBAL_TARGETS:
        root = global_root(parts)
        targets.append(
            {
                "id": target_id,
                "label": label,
                "scope": "global",
                "detail": detail,
                "path": str(root),
            }
        )
    for target_id, label, tool_dir, skills_dir in PROJECT_TARGETS:
        root = None if project is None else project / tool_dir / skills_dir
        targets.append(
            {
                "id": target_id,
                "label": label,
                "scope": "project",
                "detail": "입력한 프로젝트 안에서만 읽습니다.",
                "path": None if root is None else str(root),
            }
        )
    return targets


def destination_for(target_id: str, project: Path | None) -> Path:
    for item_id, _label, parts, _detail in GLOBAL_TARGETS:
        if item_id == target_id:
            return global_root(parts)
    for item_id, _label, tool_dir, skills_dir in PROJECT_TARGETS:
        if item_id == target_id:
            if project is None:
                raise InstallError("프로젝트 폴더를 입력해 주세요.")
            return project / tool_dir / skills_dir
    raise InstallError("설치 위치를 알지 못합니다.")


def installed_map(skills: list[dict], targets: list[dict]) -> dict:
    status: dict[str, dict[str, bool]] = {}
    for skill in skills:
        status[skill["id"]] = {}
        for target in targets:
            root = target.get("path")
            ready = False
            if root:
                ready = (Path(root) / skill["id"] / "SKILL.md").is_file()
            status[skill["id"]][target["id"]] = ready
    return status


def github_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-skill-installer",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise InstallError(f"GitHub에서 원본을 받지 못했습니다 (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise InstallError("GitHub에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from exc


def safe_child(parent: Path, name: str) -> Path:
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise InstallError("원격 스킬 경로가 올바르지 않습니다.")
    return parent / name


def download_github_dir(repo: str, remote_path: str, ref: str, dest: Path) -> None:
    url = (
        "https://api.github.com/repos/"
        + repo
        + "/contents/"
        + urllib.parse.quote(remote_path)
        + "?ref="
        + urllib.parse.quote(ref)
    )
    entries = github_json(url)
    if not isinstance(entries, list):
        raise InstallError("원격 스킬 폴더를 찾지 못했습니다.")
    dest.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        name = str(entry.get("name", ""))
        kind = entry.get("type")
        child = safe_child(dest, name)
        if kind == "dir":
            download_github_dir(repo, str(entry["path"]), ref, child)
        elif kind == "file":
            download_url = entry.get("download_url")
            if not download_url:
                continue
            request = urllib.request.Request(download_url, headers={"User-Agent": "agent-skill-installer"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    child.write_bytes(response.read())
            except urllib.error.URLError as exc:
                raise InstallError(f"{name} 파일을 받지 못했습니다.") from exc
        elif kind == "symlink":
            continue


def prepare_source(skill_id: str) -> Path:
    if skill_id not in {item["id"] for item in discover_skills()}:
        raise InstallError("목록에 없는 스킬입니다.")
    local = REPO_ROOT / skill_id
    remote = REMOTE_SKILLS.get(skill_id)
    if (local / "SKILL.md").is_file():
        return local
    if remote is None:
        raise InstallError("설치할 스킬 파일이 없습니다.")
    staging = Path(os.environ.get("TEMP", ".")) / "agent-skill-installer" / skill_id
    if staging.exists():
        shutil.rmtree(staging)
    download_github_dir(remote["repo"], remote["path"], remote["ref"], staging)
    if not (staging / "SKILL.md").is_file():
        raise InstallError("받은 원본에 SKILL.md가 없습니다.")
    return staging


def ignore_skill_junk(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_NAMES or name.endswith(".pyc")}


def same_or_nested(left: Path, right: Path) -> bool:
    left_resolved = left.resolve()
    right_resolved = right.resolve()
    if left_resolved == right_resolved:
        return True
    try:
        left_resolved.relative_to(right_resolved)
        return True
    except ValueError:
        pass
    try:
        right_resolved.relative_to(left_resolved)
        return True
    except ValueError:
        return False


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def copy_skill(source: Path, dest_root: Path, skill_id: str) -> str:
    dest = dest_root / skill_id
    if same_or_nested(source, dest):
        raise InstallError("원본 폴더와 설치 위치가 겹칩니다.")
    dest_root.mkdir(parents=True, exist_ok=True)
    temporary = dest_root / f".{skill_id}.install-tmp"
    remove_path(temporary)
    shutil.copytree(source, temporary, ignore=ignore_skill_junk)
    if not (temporary / "SKILL.md").is_file():
        remove_path(temporary)
        raise InstallError("복사된 스킬에 SKILL.md가 없습니다.")
    existed = dest.exists() or dest.is_symlink()
    remove_path(dest)
    temporary.rename(dest)
    return "replaced" if existed else "installed"


def install_selection(skill_ids: list[str], target_ids: list[str], project_raw: str) -> dict:
    with INSTALL_LOCK:
        return _install_selection(skill_ids, target_ids, project_raw)


def _install_selection(skill_ids: list[str], target_ids: list[str], project_raw: str) -> dict:
    known = {item["id"] for item in discover_skills()}
    allowed_targets = {item[0] for item in GLOBAL_TARGETS} | {item[0] for item in PROJECT_TARGETS}
    if not skill_ids or not target_ids:
        raise InstallError("스킬과 설치 위치를 하나 이상 선택해 주세요.")
    if any(skill_id not in known for skill_id in skill_ids):
        raise InstallError("목록에 없는 스킬이 포함되어 있습니다.")
    if any(target_id not in allowed_targets for target_id in target_ids):
        raise InstallError("알 수 없는 설치 위치입니다.")
    needs_project = any(target_id.endswith("-project") for target_id in target_ids)
    project = project_dir(project_raw) if needs_project else None

    sources: dict[str, Path] = {}
    prepare_errors: dict[str, str] = {}
    for skill_id in skill_ids:
        try:
            sources[skill_id] = prepare_source(skill_id)
        except InstallError as exc:
            prepare_errors[skill_id] = str(exc)

    results = []
    for skill_id in skill_ids:
        for target_id in target_ids:
            if skill_id in prepare_errors:
                results.append(
                    {
                        "skill": skill_id,
                        "target": target_id,
                        "ok": False,
                        "error": prepare_errors[skill_id],
                    }
                )
                continue
            try:
                dest_root = destination_for(target_id, project)
                action = copy_skill(sources[skill_id], dest_root, skill_id)
                results.append(
                    {
                        "skill": skill_id,
                        "target": target_id,
                        "ok": True,
                        "action": action,
                        "path": str(dest_root / skill_id),
                    }
                )
            except InstallError as exc:
                results.append(
                    {
                        "skill": skill_id,
                        "target": target_id,
                        "ok": False,
                        "error": str(exc),
                    }
                )
            except OSError as exc:
                results.append(
                    {
                        "skill": skill_id,
                        "target": target_id,
                        "ok": False,
                        "error": f"폴더를 쓰지 못했습니다. {exc.strerror or exc}",
                    }
                )
    return {"ok": all(item["ok"] for item in results), "results": results}


def catalog_payload(project_raw: str) -> dict:
    project_error = ""
    project = None
    if project_raw.strip():
        try:
            project = project_dir(project_raw)
        except InstallError as exc:
            project_error = str(exc)
    skills = discover_skills()
    targets = target_catalog(project)
    return {
        "repo": str(REPO_ROOT),
        "skills": skills,
        "targets": targets,
        "installed": installed_map(skills, targets),
        "projectError": project_error,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SkillInstaller/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in {"127.0.0.1", "localhost"}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _reject(self, code: int) -> None:
        body = json.dumps({"ok": False, "error": "요청을 처리하지 못했습니다."}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._reject(403)
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            body = INDEX_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/catalog":
            query = urllib.parse.parse_qs(parsed.query)
            project = query.get("project", [""])[0]
            self._send_json(200, catalog_payload(project))
            return
        self._reject(404)

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._origin_allowed():
            self._reject(403)
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/install":
            self._reject(404)
            return
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            self._send_json(400, {"ok": False, "error": "JSON 요청만 받습니다."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 65536:
            self._send_json(400, {"ok": False, "error": "요청 크기가 올바르지 않습니다."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "요청을 읽지 못했습니다."})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "요청 형식이 올바르지 않습니다."})
            return
        skills = payload.get("skills")
        targets = payload.get("targets")
        project = payload.get("projectPath", "")
        if not isinstance(skills, list) or not isinstance(targets, list) or not isinstance(project, str):
            self._send_json(400, {"ok": False, "error": "요청 형식이 올바르지 않습니다."})
            return
        if not all(isinstance(item, str) for item in skills + targets):
            self._send_json(400, {"ok": False, "error": "요청 형식이 올바르지 않습니다."})
            return
        try:
            result = install_selection(skills, targets, project)
        except InstallError as exc:
            self._send_json(400, {"ok": False, "error": str(exc), "results": []})
            return
        self._send_json(200, result)


def main() -> None:
    configure_stdio()
    parser = argparse.ArgumentParser(description="스킬 설치 페이지를 이 컴퓨터에서 엽니다.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not INDEX_PATH.is_file():
        print(f"페이지 파일이 없습니다: {INDEX_PATH}", file=sys.stderr)
        sys.exit(1)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"포트 {args.port}를 열지 못했습니다. {exc}", file=sys.stderr)
        sys.exit(1)
    url = f"http://127.0.0.1:{args.port}"
    print(f"스킬 설치 페이지: {url}", flush=True)
    print("이 창을 닫으면 설치 페이지도 멈춥니다.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n설치 페이지를 멈췄습니다.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
