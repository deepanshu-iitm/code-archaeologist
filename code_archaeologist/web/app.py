"""
Web Application Module

FastAPI web interface for the Code Archaeologist tool.
"""

import asyncio
import os
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..core.parser import MultiLanguageParser
from ..core.graph_builder import GraphBuilder
from ..core.query_engine import GraphRAGQueryEngine, LLMProvider
from ..utils.env_loader import EnvLoader


class QueryRequest(BaseModel):
    """Request model for queries."""
    query: str
    llm_provider: str = "gemini"
    api_key: Optional[str] = None
    model: Optional[str] = None


class IngestRequest(BaseModel):
    """Request model for ingestion."""
    repository_path: str
    clear_existing: bool = False
    exclude_patterns: list[str] = []


def create_app(neo4j_uri: str = "bolt://localhost:7687",
               neo4j_user: str = "neo4j",
               neo4j_password: str = "password") -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Code Archaeologist",
        description="GraphRAG-Powered Codebase Analysis Assistant",
        version="0.1.0"
    )
    
    # Store configuration
    app.state.neo4j_uri = neo4j_uri
    app.state.neo4j_user = neo4j_user
    app.state.neo4j_password = neo4j_password
    
    # Setup templates
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))
    
    # Setup static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        """Home page."""
        return templates.TemplateResponse("index.html", {"request": request})
    
    @app.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        # Test Neo4j connection
        graph_builder = GraphBuilder(
            app.state.neo4j_uri,
            app.state.neo4j_user,
            app.state.neo4j_password
        )
        
        neo4j_status = "connected" if graph_builder.driver else "disconnected"
        graph_builder.close()
        
        return {
            "status": "healthy",
            "neo4j": neo4j_status,
            "version": "0.1.0"
        }
    
    @app.get("/api/stats")
    async def get_graph_stats():
        """Get knowledge graph statistics."""
        graph_builder = GraphBuilder(
            app.state.neo4j_uri,
            app.state.neo4j_user,
            app.state.neo4j_password
        )
        
        if not graph_builder.driver:
            raise HTTPException(status_code=503, detail="Neo4j connection failed")
        
        try:
            stats = graph_builder.get_graph_stats()
            return stats
        finally:
            graph_builder.close()
    
    @app.post("/api/ingest")
    async def ingest_repository(request: IngestRequest):
        """Ingest a repository into the knowledge graph."""
        if not Path(request.repository_path).exists():
            raise HTTPException(status_code=400, detail="Repository path does not exist")
        
        # Initialize components
        parser = MultiLanguageParser()
        graph_builder = GraphBuilder(
            app.state.neo4j_uri,
            app.state.neo4j_user,
            app.state.neo4j_password
        )
        
        if not graph_builder.driver:
            raise HTTPException(status_code=503, detail="Neo4j connection failed")
        
        try:
            # Initialize schema
            graph_builder.initialize_schema()
            
            # Clear existing data if requested
            if request.clear_existing:
                graph_builder.clear_graph()
            
            # Parse repository
            exclude_patterns = request.exclude_patterns if request.exclude_patterns else None
            parsed_files = parser.parse_repository(request.repository_path, exclude_patterns)
            
            if not parsed_files:
                raise HTTPException(status_code=400, detail="No supported files found")
            
            # Build knowledge graph
            success = graph_builder.build_graph_from_files(parsed_files)
            
            if not success:
                raise HTTPException(status_code=500, detail="Failed to build knowledge graph")
            
            # Get final statistics
            stats = graph_builder.get_graph_stats()
            
            return {
                "success": True,
                "message": "Repository ingested successfully",
                "files_processed": len(parsed_files),
                "stats": stats
            }
        
        finally:
            graph_builder.close()
    
    @app.post("/api/query")
    async def query_codebase(request: QueryRequest):
        """Query the codebase using natural language."""
        # Validate API key
        api_key = request.api_key
        if not api_key:
            api_key = EnvLoader.get_gemini_api_key()
        
        if not api_key:
            raise HTTPException(
                status_code=400, 
                detail=f"API key required for {request.llm_provider}"
            )
        
        # Initialize components
        graph_builder = GraphBuilder(
            app.state.neo4j_uri,
            app.state.neo4j_user,
            app.state.neo4j_password
        )
        
        if not graph_builder.driver:
            raise HTTPException(status_code=503, detail="Neo4j connection failed")
        
        try:
            # Initialize query engine
            query_engine = GraphRAGQueryEngine(
                graph_builder=graph_builder,
                llm_provider=LLMProvider(request.llm_provider),
                api_key=api_key,
                model_name=request.model
            )
            
            # Execute query
            result = await query_engine.query(request.query)
            
            return {
                "answer": result.answer,
                "cypher_queries": result.cypher_queries,
                "execution_time": result.execution_time,
                "complexity": result.plan.estimated_complexity,
                "data_points": len(result.raw_data)
            }
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        
        finally:
            graph_builder.close()
    
    @app.get("/api/suggestions")
    async def get_query_suggestions():
        """Get query suggestions based on the current codebase."""
        graph_builder = GraphBuilder(
            app.state.neo4j_uri,
            app.state.neo4j_user,
            app.state.neo4j_password
        )
        
        if not graph_builder.driver:
            raise HTTPException(status_code=503, detail="Neo4j connection failed")
        
        try:
            stats = graph_builder.get_graph_stats()
            
            # Create a dummy query engine to get suggestions
            query_engine = GraphRAGQueryEngine(
                graph_builder=graph_builder,
                llm_provider=LLMProvider.OPENAI,
                api_key="dummy"  # Not used for suggestions
            )
            
            suggestions = query_engine.get_query_suggestions(stats)
            return {"suggestions": suggestions}
        
        finally:
            graph_builder.close()
    
    return app


# For development
if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
