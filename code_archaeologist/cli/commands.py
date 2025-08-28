"""
CLI Commands Module

Provides command-line interface for the Code Archaeologist tool.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from rich.panel import Panel

from ..core.parser import MultiLanguageParser
from ..core.graph_builder import GraphBuilder
from ..core.query_engine import GraphRAGQueryEngine, LLMProvider
from ..utils.env_loader import env_loader, EnvLoader
from ..utils.git_helper import handle_github_url, GitHelper


console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """The Code Archaeologist: GraphRAG-Powered Codebase Analysis"""
    pass


@cli.command()
@click.argument('repository_path')
@click.option('--neo4j-uri', help='Neo4j database URI (default from .env or bolt://localhost:7687)')
@click.option('--neo4j-user', help='Neo4j username (default from .env or neo4j)')
@click.option('--neo4j-password', help='Neo4j password (default from .env or password)')
@click.option('--clear-existing', is_flag=True, help='Clear existing graph data')
@click.option('--exclude', multiple=True, help='Exclude patterns (e.g., "*/node_modules/*")')
def ingest(repository_path: str, neo4j_uri: str, neo4j_user: str, 
           neo4j_password: str, clear_existing: bool, exclude: tuple):
    """Ingest a codebase into the knowledge graph."""
    
    console.print(Panel.fit(
        "[bold blue]Code Archaeologist[/bold blue] - Codebase Ingestion",
        border_style="blue"
    ))
    
    # Handle GitHub URLs
    if GitHelper.is_github_url(repository_path):
        console.print(f"[yellow]GitHub URL detected: {repository_path}[/yellow]")
        console.print("[yellow]Code Archaeologist requires a local directory.[/yellow]")
        
        repo_info = GitHelper.extract_repo_info(repository_path)
        if repo_info:
            console.print(f"[cyan]Suggestion: git clone {repo_info['clone_url']}[/cyan]")
            console.print("[cyan]Then run: python -m code_archaeologist ingest /path/to/cloned/repo[/cyan]")
        
        sys.exit(1)
    
    # Validate local path
    if not os.path.exists(repository_path):
        console.print(f"[red]Error: Directory '{repository_path}' does not exist.[/red]")
        sys.exit(1)
    
    if not os.path.isdir(repository_path):
        console.print(f"[red]Error: '{repository_path}' is not a directory.[/red]")
        sys.exit(1)
    
    # Get configuration from environment or use provided values
    neo4j_config = EnvLoader.get_neo4j_config()
    neo4j_uri = neo4j_uri or neo4j_config['uri']
    neo4j_user = neo4j_user or neo4j_config['user']
    neo4j_password = neo4j_password or neo4j_config['password']
    
    # Initialize components
    parser = MultiLanguageParser()
    graph_builder = GraphBuilder(neo4j_uri, neo4j_user, neo4j_password)
    
    if not graph_builder.driver:
        console.print("[red]Failed to connect to Neo4j. Please check your connection settings.[/red]")
        sys.exit(1)
    
    try:
        # Initialize schema
        console.print("Initializing graph schema...")
        graph_builder.initialize_schema()
        
        # Clear existing data if requested
        if clear_existing:
            console.print("Clearing existing graph data...")
            graph_builder.clear_graph()
        
        # Parse repository
        console.print(f"Parsing repository: [cyan]{repository_path}[/cyan]")
        
        exclude_patterns = list(exclude) if exclude else None
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Parsing files...", total=None)
            parsed_files = parser.parse_repository(repository_path, exclude_patterns)
            progress.update(task, description=f"Parsed {len(parsed_files)} files")
        
        if not parsed_files:
            console.print("[red]No supported files found in the repository.[/red]")
            return
        
        # Display parsing results
        table = Table(title="Parsing Results")
        table.add_column("Language", style="cyan")
        table.add_column("Files", justify="right", style="green")
        table.add_column("Functions", justify="right", style="yellow")
        table.add_column("Classes", justify="right", style="magenta")
        
        lang_stats = {}
        for parsed_file in parsed_files:
            lang = parsed_file.language
            if lang not in lang_stats:
                lang_stats[lang] = {"files": 0, "functions": 0, "classes": 0}
            lang_stats[lang]["files"] += 1
            lang_stats[lang]["functions"] += len(parsed_file.functions)
            lang_stats[lang]["classes"] += len(parsed_file.classes)
        
        for lang, stats in lang_stats.items():
            table.add_row(
                lang.title(),
                str(stats["files"]),
                str(stats["functions"]),
                str(stats["classes"])
            )
        
        console.print(table)
        
        # Build knowledge graph
        console.print("Building knowledge graph...")
        success = graph_builder.build_graph_from_files(parsed_files)
        
        if success:
            # Display graph statistics
            stats = graph_builder.get_graph_stats()
            if stats:
                console.print("\n[bold green]Graph Statistics:[/bold green]")
                console.print(f"   - Total Nodes: {stats.get('total_nodes', 0)}")
                console.print(f"   - Total Relationships: {stats.get('total_relationships', 0)}")
                
                for node_type, count in stats.get('nodes', {}).items():
                    if count > 0:
                        console.print(f"   - {node_type}: {count}")
            
            console.print("\n[bold green]Codebase successfully ingested![/bold green]")
            console.print("You can now query the codebase using: [cyan]code-archaeologist query[/cyan]")
        else:
            console.print("[red]Failed to build knowledge graph.[/red]")
            sys.exit(1)
    
    finally:
        graph_builder.close()


@cli.command()
@click.argument('query_text')
@click.option('--neo4j-uri', default='bolt://localhost:7687', help='Neo4j database URI')
@click.option('--neo4j-user', default='neo4j', help='Neo4j username')
@click.option('--neo4j-password', default='password', help='Neo4j password')
@click.option('--llm-provider', type=click.Choice(['gemini']), 
              default='gemini', help='LLM provider to use')
@click.option('--api-key', help='API key for LLM provider')
@click.option('--model', help='Specific model to use')
@click.option('--show-cypher', is_flag=True, help='Show generated Cypher queries')
@click.option('--show-raw-data', is_flag=True, help='Show raw graph data')
def query(query_text: str, neo4j_uri: str, neo4j_user: str, neo4j_password: str,
          llm_provider: str, api_key: Optional[str], model: Optional[str],
          show_cypher: bool, show_raw_data: bool):
    """Query the codebase using natural language."""
    
    console.print(Panel.fit(
        "[bold blue]Code Archaeologist[/bold blue] - Codebase Query",
        border_style="blue"
    ))
    
    # Initialize components
    graph_builder = GraphBuilder(neo4j_uri, neo4j_user, neo4j_password)
    
    if not graph_builder.driver:
        console.print("[red]Failed to connect to Neo4j. Please check your connection settings.[/red]")
        sys.exit(1)
    
    # Get configuration from environment or use provided values
    neo4j_config = EnvLoader.get_neo4j_config()
    neo4j_uri = neo4j_uri or neo4j_config['uri']
    neo4j_user = neo4j_user or neo4j_config['user']
    neo4j_password = neo4j_password or neo4j_config['password']
    
    # Check if API key is provided or available in environment
    if not api_key:
        api_key = EnvLoader.get_gemini_api_key()
    
    if not api_key:
        console.print(f"[red]Gemini API key required. Please set GEMINI_API_KEY in your .env file or use --api-key option.[/red]")
        console.print(f"[yellow]Get your API key from: https://makersuite.google.com/app/apikey[/yellow]")
        sys.exit(1)
    
    try:
        # Initialize query engine
        query_engine = GraphRAGQueryEngine(
            graph_builder=graph_builder,
            llm_provider=LLMProvider(llm_provider),
            api_key=api_key,
            model_name=model
        )
        
        console.print(f"[bold]Query:[/bold] {query_text}")
        console.print()
        
        # Execute query
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Processing query...", total=None)
            
            # Run async query
            result = asyncio.run(query_engine.query(query_text))
            
            progress.update(task, description="Query completed")
        
        # Display results
        console.print("[bold green]Answer:[/bold green]")
        console.print(Panel(Markdown(result.answer), border_style="green"))
        
        # Show execution details if requested
        if show_cypher and result.cypher_queries:
            console.print("\n[bold]Generated Cypher Queries:[/bold]")
            for i, cypher in enumerate(result.cypher_queries, 1):
                console.print(f"[cyan]Query {i}:[/cyan]")
                console.print(Panel(cypher, border_style="cyan"))
        
        if show_raw_data and result.raw_data:
            console.print("\n[bold]Raw Graph Data:[/bold]")
            for i, data in enumerate(result.raw_data[:5], 1):  # Limit to first 5 items
                console.print(f"[yellow]Data {i}:[/yellow]")
                console.print(Panel(str(data), border_style="yellow"))
        
        # Show execution stats
        console.print(f"\nExecution time: {result.execution_time:.2f}s")
        console.print(f"Complexity: {result.plan.estimated_complexity}")
        console.print(f"Graph queries: {len(result.cypher_queries)}")
        console.print(f"Data points: {len(result.raw_data)}")
    
    finally:
        graph_builder.close()


@cli.command()
@click.option('--neo4j-uri', default='bolt://localhost:7687', help='Neo4j database URI')
@click.option('--neo4j-user', default='neo4j', help='Neo4j username')
@click.option('--neo4j-password', default='password', help='Neo4j password')
def stats(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """Show knowledge graph statistics."""
    
    console.print(Panel.fit(
        "[bold blue]Code Archaeologist[/bold blue] - Graph Statistics",
        border_style="blue"
    ))
    
    graph_builder = GraphBuilder(neo4j_uri, neo4j_user, neo4j_password)
    
    if not graph_builder.driver:
        console.print("[red]Failed to connect to Neo4j.[/red]")
        sys.exit(1)
    
    try:
        stats = graph_builder.get_graph_stats()
        
        if not stats:
            console.print("[red]No graph data found or failed to retrieve statistics.[/red]")
            return
        
        # Nodes table
        nodes_table = Table(title="Node Statistics")
        nodes_table.add_column("Node Type", style="cyan")
        nodes_table.add_column("Count", justify="right", style="green")
        
        for node_type, count in stats.get('nodes', {}).items():
            if count > 0:
                nodes_table.add_row(node_type, str(count))
        
        console.print(nodes_table)
        
        # Relationships table
        rels_table = Table(title="Relationship Statistics")
        rels_table.add_column("Relationship Type", style="magenta")
        rels_table.add_column("Count", justify="right", style="green")
        
        for rel_type, count in stats.get('relationships', {}).items():
            if count > 0:
                rels_table.add_row(rel_type, str(count))
        
        console.print(rels_table)
        
        # Summary
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"   - Total Nodes: {stats.get('total_nodes', 0)}")
        console.print(f"   - Total Relationships: {stats.get('total_relationships', 0)}")
    
    finally:
        graph_builder.close()


@cli.command()
@click.option('--host', default='localhost', help='Host to bind the server to')
@click.option('--port', default=8000, help='Port to bind the server to')
@click.option('--neo4j-uri', default='bolt://localhost:7687', help='Neo4j database URI')
@click.option('--neo4j-user', default='neo4j', help='Neo4j username')
@click.option('--neo4j-password', default='password', help='Neo4j password')
def serve(host: str, port: int, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """Start the web interface server."""
    
    console.print(Panel.fit(
        "[bold blue]Code Archaeologist[/bold blue] - Web Server",
        border_style="blue"
    ))
    
    try:
        import uvicorn
        from ..web.app import create_app
        
        # Get configuration from environment or use provided values
        neo4j_config = EnvLoader.get_neo4j_config()
        web_config = EnvLoader.get_web_config()
        
        neo4j_uri = neo4j_uri or neo4j_config['uri']
        neo4j_user = neo4j_user or neo4j_config['user']
        neo4j_password = neo4j_password or neo4j_config['password']
        host = host or web_config['host']
        port = port or web_config['port']
        
        # Create the FastAPI app with configuration
        app = create_app(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password
        )
        
        console.print(f"Starting server at http://{host}:{port}")
        console.print("Press Ctrl+C to stop the server")
        
        uvicorn.run(app, host=host, port=port, log_level="info")
    
    except ImportError:
        console.print("[red]Web dependencies not installed. Run: pip install uvicorn fastapi[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Failed to start server: {e}[/red]")
        sys.exit(1)


if __name__ == '__main__':
    cli()
