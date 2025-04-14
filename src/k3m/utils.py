import contextlib
import subprocess
import sys
from typing import Optional
from rich.console import Console
from halo import Halo

console = Console()

def get_multipass_path() -> str:
    result = subprocess.run(['which', 'multipass'], capture_output=True, text=True)
    return result.stdout.strip()


def check_multipass_access_available() -> bool:
    result = subprocess.run([get_multipass_path(), 'list'], capture_output=True, text=True)
    return result.returncode == 0

def check_multipass_status() -> bool:
    multipass_path = get_multipass_path()
    if not multipass_path:
        return False
    
    return check_multipass_access_available()

def ensure_multipass() -> None:
    """Ensure multipass is available and properly configured"""
    if not check_multipass_status():
        console.print(f"[red]Error:[/red] Multipass is not installed or not accessible")
        console.print("\nFor more help, visit: https://canonical.com/multipass/install")
        sys.exit(1)

def process(cmd: str, message: Optional[str] = None, on_success: Optional[str] = None) -> str:
    """Run a shell command with Halo spinner for status indication"""
    spinner = Halo(text=message or "Processing...", spinner='dots')
    spinner.start()
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            spinner.fail(f"Error: {result.stderr}")
            raise RuntimeError(f"Command failed: {cmd}\nError: {result.stderr}")
        
        if on_success:
            spinner.succeed(on_success)
        else:
            spinner.stop()
        
        return result.stdout.strip()
    except Exception as e:
        spinner.fail(f"Error: {str(e)}")
        raise