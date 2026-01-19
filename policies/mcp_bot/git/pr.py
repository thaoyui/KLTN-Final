"""Git and PR Automation"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

import requests

# Try PyGithub, fallback to requests
try:
    from github import Github
    HAS_PYGITHUB = True
    _PYGITHUB_AVAILABLE = True
except ImportError as e:
    HAS_PYGITHUB = False
    _PYGITHUB_AVAILABLE = False
    _PYGITHUB_ERROR = str(e)


class GitRepo:
    """Git operations for policy repository"""
    
    def __init__(self, repo_url: str, auth_user: str, auth_pat: str, work_dir: str):
        self.repo_url = repo_url
        self.auth_user = auth_user
        self.auth_pat = auth_pat
        self.work_dir = Path(work_dir)
        
        # Extract repo owner/name for API
        if "github.com" in repo_url:
            parts = repo_url.replace("https://github.com/", "").replace(".git", "").split("/")
            self.repo_owner = parts[0]
            self.repo_name = parts[1] if len(parts) > 1 else ""
        
        self.auth_url = repo_url.replace("https://", f"https://{auth_user}:{auth_pat}@")
    
    def clone(self, branch: str = "main") -> None:
        """Clone repository"""
        print(f"[DEBUG] 🔍 Git Clone Debug:")
        print(f"  - Repo URL: {self.repo_url}")
        print(f"  - Auth User: {self.auth_user}")
        print(f"  - Auth URL (masked): {self.auth_url.split('@')[0]}@<hidden>/{'/'.join(self.auth_url.split('/')[-2:])}")
        print(f"  - Work Dir: {self.work_dir}")
        print(f"  - Branch: {branch}")
        
        # Test authentication first
        print(f"[DEBUG] 🧪 Testing GitHub authentication...")
        try:
            test_url = f"https://api.github.com/user"
            import urllib.request
            import base64
            import json
            import ssl
            import certifi
            
            credentials = f"{self.auth_user}:{self.auth_pat}".encode()
            auth_header = base64.b64encode(credentials).decode()
            
            req = urllib.request.Request(test_url)
            req.add_header("Authorization", f"Basic {auth_header}")
            req.add_header("Accept", "application/vnd.github+json")
            
            # Use SSL context with certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            
            try:
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    user_data = json.loads(resp.read())
                    print(f"[DEBUG] ✅ GitHub auth SUCCESS")
                    print(f"  - Authenticated as: {user_data.get('login', 'unknown')}")
                    print(f"  - User ID: {user_data.get('id', 'unknown')}")
                    
                    # Check repo access
                    repo_test_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}"
                    repo_req = urllib.request.Request(repo_test_url)
                    repo_req.add_header("Authorization", f"Basic {auth_header}")
                    repo_req.add_header("Accept", "application/vnd.github+json")
                    
                    try:
                        with urllib.request.urlopen(repo_req, timeout=10, context=ctx) as repo_resp:
                            repo_data = json.loads(repo_resp.read())
                            print(f"[DEBUG] ✅ Repo access SUCCESS")
                            print(f"  - Repo: {repo_data.get('full_name', 'unknown')}")
                            print(f"  - Private: {repo_data.get('private', False)}")
                            permissions = repo_data.get('permissions', {})
                            print(f"  - Permissions: read={permissions.get('pull', False)}, write={permissions.get('push', False)}, admin={permissions.get('admin', False)}")
                    except urllib.error.HTTPError as e:
                        detail = e.read().decode("utf-8", errors="ignore")
                        print(f"[DEBUG] ❌ Repo access FAILED: {e.code} {e.reason}")
                        print(f"[DEBUG]   Detail: {detail[:200]}")
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="ignore")
                print(f"[DEBUG] ❌ GitHub auth FAILED: {e.code} {e.reason}")
                print(f"[DEBUG]   Detail: {detail[:200]}")
                print(f"[DEBUG]   Possible causes:")
                print(f"     - Invalid username or PAT")
                print(f"     - PAT expired or revoked")
                print(f"     - PAT doesn't have required scopes")
                print(f"[DEBUG]   🔧 Fix: Create new PAT with 'repo' scope at:")
                print(f"     https://github.com/settings/tokens")
                print(f"     Required scopes: 'repo' (full control of private repositories)")
            except urllib.error.URLError as e:
                if "SSL" in str(e) or "CERTIFICATE" in str(e):
                    print(f"[DEBUG] ❌ SSL certificate error: {e}")
                    print(f"[DEBUG]   Fix: Install certifi: pip install certifi")
                else:
                    print(f"[DEBUG] ❌ Network error: {e}")
        except Exception as e:
            print(f"[DEBUG] ⚠️ Auth test error: {e}")
        
        # Proceed with clone
        if self.work_dir.exists():
            subprocess.run(["rm", "-rf", str(self.work_dir)], check=True)
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
        print(f"[DEBUG] 🔄 Cloning repository...")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, self.auth_url, str(self.work_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"[DEBUG] ✅ Clone successful")
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG] ❌ Clone failed:")
            print(f"  - Return code: {e.returncode}")
            print(f"  - stderr: {e.stderr}")
            print(f"  - stdout: {e.stdout}")
            raise
    
    def checkout_branch(self, branch: str) -> None:
        """Create and checkout branch"""
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=self.work_dir,
            check=True,
        )
    
    def commit(self, message: str, files: list[str]) -> None:
        """Commit files"""
        for f in files:
            subprocess.run(["git", "add", f], cwd=self.work_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.work_dir,
            check=True,
        )

    def get_changed_files(self, prefix: str | None = None) -> list[str]:
        """Return a list of changed files relative to repo root."""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"[DEBUG] 🔍 Git Status Output:\n{result.stdout}")
        files: list[str] = []
        for raw_line in result.stdout.splitlines():
            # git status --porcelain returns "XY Path"
            # XY are status codes (2 chars), followed by space
            if len(raw_line) < 4:
                continue
            
            # Extract path (everything after first 3 chars)
            path_part = raw_line[3:]
            
            if "->" in path_part:
                path_part = path_part.split("->", 1)[1].strip()
            path = path_part.strip()
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue
            files.append(path)
        return files
    
    def get_diff(self, file_path: str) -> str:
        """Get diff for a specific file (or content if new)"""
        # Check if file is untracked
        status = subprocess.run(
            ["git", "status", "--porcelain", file_path],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            check=False
        )
        if "??" in status.stdout:
            # Untracked: return full content
            try:
                content = (self.work_dir / file_path).read_text(encoding="utf-8", errors="replace")
                return f"New File: {file_path}\n\n{content}"
            except Exception as e:
                return f"Error reading new file: {e}"
        
        # Tracked: return diff
        # Try unstaged diff first
        result = subprocess.run(
            ["git", "diff", "--color=always", file_path],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            check=False
        )
        if result.stdout.strip():
            return result.stdout
        
        # Try staged diff (if added but not committed)
        result = subprocess.run(
            ["git", "diff", "--cached", "--color=always", file_path],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            check=False
        )
        return result.stdout
    
    def push(self, branch: str) -> None:
        """Push branch"""
        print(f"[DEBUG] 🔍 Git Push Debug:")
        print(f"  - Branch: {branch}")
        print(f"  - Work Dir: {self.work_dir}")
        
        # Check current remote
        try:
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"[DEBUG]   Remote config:")
            for line in result.stdout.strip().split("\n"):
                print(f"     {line}")
        except Exception as e:
            print(f"[DEBUG]   ⚠️ Could not check remote: {e}")
        
        # Check if branch exists
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            current_branch = result.stdout.strip()
            print(f"[DEBUG]   Current branch: {current_branch}")
        except Exception as e:
            print(f"[DEBUG]   ⚠️ Could not check current branch: {e}")
        
        print(f"[DEBUG] 🔄 Pushing branch {branch}...")
        try:
            result = subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=self.work_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"[DEBUG] ✅ Push successful")
            print(f"  - Output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG] ❌ Push failed:")
            print(f"  - Return code: {e.returncode}")
            print(f"  - stderr: {e.stderr}")
            print(f"  - stdout: {e.stdout}")
            
            # Additional diagnosis
            if "403" in e.stderr or "Permission" in e.stderr:
                print(f"[DEBUG]   🔍 Diagnosis: Authentication/permission issue")
                print(f"     - PAT missing 'repo' scope (required for push)")
                print(f"     - Create new PAT at: https://github.com/settings/tokens")
                print(f"     - Required scopes: 'repo' (full control)")
                print(f"     - Verify username '{self.auth_user}' matches PAT owner")
                print(f"     - Current PAT format: {self.auth_pat[:20]}...")
                
                # Try to get more info about PAT
                try:
                    import urllib.request
                    import base64
                    import ssl
                    import certifi
                    import json
                    
                    test_url = "https://api.github.com/user"
                    credentials = f"{self.auth_user}:{self.auth_pat}".encode()
                    auth_header = base64.b64encode(credentials).decode()
                    
                    req = urllib.request.Request(test_url)
                    req.add_header("Authorization", f"Basic {auth_header}")
                    req.add_header("Accept", "application/vnd.github+json")
                    
                    ctx = ssl.create_default_context(cafile=certifi.where())
                    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                        user_data = json.loads(resp.read())
                        print(f"[DEBUG]   ✅ PAT is valid for user: {user_data.get('login')}")
                        print(f"[DEBUG]   ⚠️ But PAT doesn't have 'repo' scope for push/PR operations")
                except Exception:
                    pass
            elif "already exists" in e.stderr or "branch already exists" in e.stderr:
                print(f"[DEBUG]   ℹ️ Branch already exists on remote")
            
            raise
    
    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Optional[Dict]:
        """Create GitHub PR via PyGithub (or requests fallback)"""
        if not self.repo_owner or not self.repo_name:
            return None
        
        # Use PyGithub if available (preferred)
        if HAS_PYGITHUB:
            try:
                g = Github(self.auth_pat)
                
                # Get repo
                try:
                    user = g.get_user(self.repo_owner)
                    repo_obj = user.get_repo(self.repo_name)
                except Exception:
                    repo_obj = g.get_repo(f"{self.repo_owner}/{self.repo_name}")
                
                # Create PR
                pull_request = repo_obj.create_pull(
                    title=title,
                    body=body,
                    head=head,
                    base=base,
                )
                
                return {
                    "html_url": pull_request.html_url,
                    "number": pull_request.number,
                    "state": pull_request.state,
                    "title": pull_request.title,
                }
            except Exception as e:
                print(f"Warning: PyGithub PR creation failed: {e}, falling back to requests")
        
        # Fallback to requests API
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/pulls"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.auth_pat}",
        }
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Warning: Failed to create PR via API: {e}")
            return None


def create_pr(
    repo_url: str,
    auth_user: str,
    auth_pat: str,
    branch: str,
    title: str,
    body: str,
    base: str = "main",
) -> Optional[str]:
    """Create PR and return URL (using PyGithub if available, else requests)"""
    print(f"[DEBUG] 🔍 PR Creation Debug:")
    print(f"  - Repo: {repo_url}")
    print(f"  - User: {auth_user}")
    print(f"  - Branch: {branch}")
    print(f"  - Base: {base}")
    print(f"  - Using PyGithub: {HAS_PYGITHUB}")
    if not HAS_PYGITHUB:
        print(f"  ⚠️  PyGithub NOT INSTALLED")
        print(f"     Install: pip3 install PyGithub")
        print(f"     Or run: ./install_deps.sh")
    
    if "github.com" not in repo_url:
        print(f"[DEBUG] ❌ Not a GitHub repo")
        return None
    
    parts = repo_url.replace("https://github.com/", "").replace(".git", "").split("/")
    if len(parts) < 2:
        print(f"[DEBUG] ❌ Invalid repo URL format")
        return None
    
    owner, repo = parts[0], parts[1]
    print(f"[DEBUG]   Owner: {owner}, Repo: {repo}")
    
    # Use PyGithub if available (preferred)
    if HAS_PYGITHUB:
        print(f"[DEBUG] 🔄 Creating PR via PyGithub...")
        try:
            g = Github(auth_pat)
            
            # Get repo - try different ways
            try:
                # Try: owner.get_repo(repo)
                user = g.get_user(owner)
                repo_obj = user.get_repo(repo)
            except Exception:
                try:
                    # Fallback: g.get_repo(f"{owner}/{repo}")
                    repo_obj = g.get_repo(f"{owner}/{repo}")
                except Exception as e:
                    print(f"[DEBUG] ❌ Could not access repo: {e}")
                    print(f"[DEBUG]   Check PAT has 'repo' scope and user has access")
                    return None
            
            print(f"[DEBUG] ✅ Repo access: {repo_obj.full_name}")
            print(f"[DEBUG]   - Private: {repo_obj.private}")
            print(f"[DEBUG]   - Permissions: {repo_obj.permissions}")
            
            # Verify branch exists
            try:
                branches = [b.name for b in repo_obj.get_branches()]
                print(f"[DEBUG]   Available branches: {branches[:10]}")
                if branch not in branches:
                    print(f"[DEBUG] ⚠️ Branch '{branch}' not found on remote")
                    print(f"[DEBUG]     Available: {', '.join(branches[:10])}")
                    print(f"[DEBUG]     ℹ️  Branch must exist on remote before creating PR")
                    print(f"[DEBUG]     ℹ️  Git push failed earlier - push branch first")
                    return None  # Can't create PR if branch doesn't exist
            except Exception as e:
                print(f"[DEBUG] ⚠️ Could not list branches: {e}")
            
            # Create PR
            print(f"[DEBUG] 🔄 Creating PR: {branch} -> {base}")
            pull_request = repo_obj.create_pull(
                title=title,
                body=body,
                head=branch,
                base=base,
            )
            
            pr_url = pull_request.html_url
            print(f"[DEBUG] ✅ PR created successfully: {pr_url}")
            print(f"  - PR #{pull_request.number}")
            print(f"  - State: {pull_request.state}")
            return pr_url
            
        except Exception as e:
            print(f"[DEBUG] ❌ PyGithub PR creation failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Check specific error types
            error_str = str(e).lower()
            if "403" in error_str or "permission" in error_str or "not accessible" in error_str:
                print(f"[DEBUG]   🔍 Diagnosis: Permission denied (403)")
                print(f"     - Fine-grained PAT may not work for PR creation")
                print(f"     - Create Classic PAT with 'repo' scope:")
                print(f"       https://github.com/settings/tokens")
                print(f"       Select: repo (Full control)")
                print(f"       Token format: ghp_... (not github_pat_...)")
                print(f"     - Or configure Fine-grained PAT:")
                print(f"       Contents: Read and write")
                print(f"       Pull requests: Read and write")
            elif "422" in error_str or "validation" in error_str:
                print(f"[DEBUG]   🔍 Diagnosis: Validation error (422)")
                print(f"     - Branch '{branch}' might not exist on remote")
                print(f"     - Base branch '{base}' might not exist")
                print(f"     - Branch name might be invalid")
                print(f"     - Note: PR can't be created if branch doesn't exist")
            
            # Fallback to requests if PyGithub fails
            print(f"[DEBUG] ⚠️ Falling back to requests API...")
    
    # Fallback to requests API
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {auth_pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = {
        "title": title,
        "body": body,
        "head": branch,
        "base": base,
    }
    
    print(f"[DEBUG] 🔄 Creating PR via requests API...")
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"[DEBUG]   Response status: {resp.status_code}")
        
        if resp.status_code == 201:
            pr_data = resp.json()
            pr_url = pr_data.get("html_url")
            print(f"[DEBUG] ✅ PR created: {pr_url}")
            return pr_url
        else:
            print(f"[DEBUG] ❌ PR creation failed:")
            print(f"  - Status: {resp.status_code}")
            print(f"  - Response: {resp.text[:500]}")
            
            if resp.status_code == 403:
                print(f"[DEBUG]   🔍 Diagnosis: Permission denied")
                print(f"     - PAT missing 'repo' scope")
                print(f"     - Create new PAT: https://github.com/settings/tokens")
            elif resp.status_code == 422:
                print(f"[DEBUG]   🔍 Diagnosis: Validation error")
                print(f"     - Branch '{branch}' might not exist")
                print(f"     - Base branch '{base}' might not exist")
            
            resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"[DEBUG] ❌ HTTP error: {e}")
        return None
    except Exception as e:
        print(f"[DEBUG] ❌ PR creation error: {e}")
        import traceback
        traceback.print_exc()
        return None
