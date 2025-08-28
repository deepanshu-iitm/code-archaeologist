"""
Git Helper Utility

Provides utilities for cloning GitHub repositories for analysis.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


class GitHelper:
    """Helper class for Git operations."""
    
    @staticmethod
    def is_github_url(url: str) -> bool:
        """Check if the URL is a GitHub URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower() in ['github.com', 'www.github.com']
        except:
            return False
    
    @staticmethod
    def extract_repo_info(github_url: str) -> Optional[dict]:
        """Extract repository information from GitHub URL."""
        if not GitHelper.is_github_url(github_url):
            return None
        
        try:
            # Handle different GitHub URL formats
            url = github_url.replace('https://github.com/', '').replace('http://github.com/', '')
            
            # Remove tree/branch part if present
            if '/tree/' in url:
                url = url.split('/tree/')[0]
            
            parts = url.split('/')
            if len(parts) >= 2:
                return {
                    'owner': parts[0],
                    'repo': parts[1],
                    'clone_url': f"https://github.com/{parts[0]}/{parts[1]}.git"
                }
        except:
            pass
        
        return None
    
    @staticmethod
    def clone_repository(github_url: str, target_dir: Optional[str] = None) -> Optional[str]:
        """Clone a GitHub repository to a local directory."""
        repo_info = GitHelper.extract_repo_info(github_url)
        if not repo_info:
            print(f"Invalid GitHub URL: {github_url}")
            return None
        
        if target_dir is None:
            # Create a temporary directory
            target_dir = os.path.join(tempfile.gettempdir(), f"code_archaeologist_{repo_info['repo']}")
        
        target_path = Path(target_dir)
        
        # If directory already exists, ask user
        if target_path.exists():
            print(f"Directory {target_dir} already exists.")
            response = input("Do you want to use the existing directory? (y/n): ").lower().strip()
            if response == 'y':
                return str(target_path)
            else:
                print("Please specify a different target directory or remove the existing one.")
                return None
        
        try:
            # Clone the repository
            print(f"Cloning {repo_info['clone_url']} to {target_dir}...")
            result = subprocess.run([
                'git', 'clone', repo_info['clone_url'], target_dir
            ], capture_output=True, text=True, check=True)
            
            print(f"Successfully cloned repository to: {target_dir}")
            return str(target_path)
            
        except subprocess.CalledProcessError as e:
            print(f"Failed to clone repository: {e}")
            print(f"Error output: {e.stderr}")
            return None
        except FileNotFoundError:
            print("Git is not installed or not in PATH. Please install Git first.")
            return None
    
    @staticmethod
    def suggest_clone_command(github_url: str) -> str:
        """Suggest a git clone command for the user."""
        repo_info = GitHelper.extract_repo_info(github_url)
        if repo_info:
            return f"git clone {repo_info['clone_url']}"
        return f"git clone {github_url}"


def handle_github_url(url: str) -> Optional[str]:
    """Handle GitHub URL by suggesting clone or attempting to clone."""
    if not GitHelper.is_github_url(url):
        return None
    
    print(f"GitHub URL detected: {url}")
    print("The Code Archaeologist works with local directories.")
    print("You have a few options:")
    print()
    
    clone_cmd = GitHelper.suggest_clone_command(url)
    print(f"1. Clone manually: {clone_cmd}")
    print("2. Let Code Archaeologist clone it for you")
    print()
    
    choice = input("Choose option (1 or 2, or 'q' to quit): ").strip().lower()
    
    if choice == '1':
        print(f"Run this command first: {clone_cmd}")
        print("Then use: python -m code_archaeologist ingest /path/to/cloned/repo")
        return None
    elif choice == '2':
        return GitHelper.clone_repository(url)
    else:
        print("Operation cancelled.")
        return None
