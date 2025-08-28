# The Code Archaeologist

A GraphRAG-powered codebase analysis assistant that combines symbolic code analysis, knowledge graphs, and advanced RAG techniques to enable natural language querying of codebases.

## Overview

The Code Archaeologist transforms unstructured source code into a queryable knowledge graph, enabling developers to ask complex structural questions about their codebase in natural language.

### Key Features

- **Multi-language AST parsing** using tree-sitter
- **Knowledge graph construction** with Neo4j
- **GraphRAG query engine** powered by LLMs
- **Natural language interface** for complex code queries
- **Structural code understanding** beyond simple text search

### Example Queries

- "Show me the full definition of the User class and list all functions that create instances of it"
- "What database models does the process_payment function interact with? Show the call chain"
- "Generate documentation for the api/v1/auth.py module"
- "Find all deprecated functions and where they're still being called"
- "If I change the calculate_tax function signature, what will be affected?"

## Architecture

The system follows a three-stage pipeline:

1. **Code Parsing**: Uses tree-sitter to generate ASTs from source files
2. **Knowledge Graph Construction**: Translates ASTs into a Neo4j graph database
3. **GraphRAG Query Engine**: Uses LLMs for query planning, graph querying, and synthesis

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### CLI Interface

```bash
# Ingest a codebase
python -m code_archaeologist ingest /path/to/repository

# Query the codebase
python -m code_archaeologist query "What does the process_payment function do?"
```

### Web Interface

```bash
python -m code_archaeologist serve
```

Then open http://localhost:8000 in your browser.

## Technical Stack

- **AST Parsing**: tree-sitter (multi-language support)
- **Graph Database**: Neo4j
- **LLM Integration**: Google Gemini
- **Web Framework**: FastAPI
- **CLI Framework**: Click

