"""
Main module entry point for the Code Archaeologist package.

Allows running the package with: python -m code_archaeologist
"""

from .cli.commands import cli

if __name__ == '__main__':
    cli()
