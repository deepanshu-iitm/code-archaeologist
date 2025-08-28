"""
Knowledge Graph Schema Definitions

Defines the node types and relationships for representing code structure
in a Neo4j graph database.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel


class NodeType(str, Enum):
    """Node types in the code knowledge graph."""
    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    VARIABLE = "Variable"
    IMPORT = "Import"
    MODULE = "Module"
    PARAMETER = "Parameter"
    RETURN_TYPE = "ReturnType"


class RelationshipType(str, Enum):
    """Relationship types in the code knowledge graph."""
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    DEFINES = "DEFINES"
    CALLS = "CALLS"
    INHERITS_FROM = "INHERITS_FROM"
    INSTANTIATES = "INSTANTIATES"
    USES = "USES"
    RETURNS = "RETURNS"
    HAS_PARAMETER = "HAS_PARAMETER"
    REFERENCES = "REFERENCES"
    DECORATES = "DECORATES"


class CodeNode(BaseModel):
    """Base model for code graph nodes."""
    id: str
    type: NodeType
    name: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    source_code: Optional[str] = None
    properties: Dict = {}


class CodeRelationship(BaseModel):
    """Model for code graph relationships."""
    source_id: str
    target_id: str
    type: RelationshipType
    properties: Dict = {}


class GraphSchema:
    """Schema utilities for the code knowledge graph."""
    
    @staticmethod
    def get_cypher_create_constraints() -> List[str]:
        """Get Cypher queries to create database constraints."""
        constraints = []
        
        # Create uniqueness constraints for each node type
        for node_type in NodeType:
            constraints.append(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{node_type.value}) "
                f"REQUIRE n.id IS UNIQUE"
            )
        
        return constraints
    
    @staticmethod
    def get_cypher_create_indexes() -> List[str]:
        """Get Cypher queries to create database indexes."""
        indexes = []
        
        # Create indexes for common search patterns
        for node_type in NodeType:
            indexes.extend([
                f"CREATE INDEX IF NOT EXISTS FOR (n:{node_type.value}) ON (n.name)",
                f"CREATE INDEX IF NOT EXISTS FOR (n:{node_type.value}) ON (n.file_path)"
            ])
        
        return indexes
    
    @staticmethod
    def node_to_cypher(node: CodeNode) -> str:
        """Convert a CodeNode to a Cypher CREATE statement."""
        properties = {
            "id": node.id,
            "name": node.name,
            **node.properties
        }
        
        if node.file_path:
            properties["file_path"] = node.file_path
        if node.line_start is not None:
            properties["line_start"] = node.line_start
        if node.line_end is not None:
            properties["line_end"] = node.line_end
        if node.source_code:
            properties["source_code"] = node.source_code
        
        # Format properties for Cypher
        props_str = ", ".join([f"{k}: ${k}" for k in properties.keys()])
        
        return f"CREATE (n:{node.type.value} {{{props_str}}})", properties
    
    @staticmethod
    def relationship_to_cypher(rel: CodeRelationship) -> str:
        """Convert a CodeRelationship to a Cypher MATCH/CREATE statement."""
        props_str = ""
        if rel.properties:
            props_str = " {" + ", ".join([f"{k}: ${k}" for k in rel.properties.keys()]) + "}"
        
        cypher = (
            f"MATCH (a {{id: $source_id}}), (b {{id: $target_id}}) "
            f"CREATE (a)-[:{rel.type.value}{props_str}]->(b)"
        )
        
        properties = {
            "source_id": rel.source_id,
            "target_id": rel.target_id,
            **rel.properties
        }
        
        return cypher, properties


# Common query templates
QUERY_TEMPLATES = {
    "find_function": """
        MATCH (f:Function {name: $function_name})
        OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
        OPTIONAL MATCH (f)-[:USES]->(var:Variable)
        RETURN f, collect(DISTINCT called) as calls, collect(DISTINCT var) as uses
    """,
    
    "find_class_methods": """
        MATCH (c:Class {name: $class_name})-[:CONTAINS]->(m:Function)
        RETURN c, collect(m) as methods
    """,
    
    "trace_call_chain": """
        MATCH path = (start:Function {name: $start_function})-[:CALLS*1..5]->(end)
        RETURN path, length(path) as depth
        ORDER BY depth
    """,
    
    "find_dependencies": """
        MATCH (f:Function {name: $function_name})
        MATCH (f)-[:CALLS*1..3]->(dep:Function)
        RETURN DISTINCT dep.name as dependency, dep.file_path as file
    """,
    
    "find_usages": """
        MATCH (target {name: $target_name})
        MATCH (user)-[:CALLS|USES|REFERENCES]->(target)
        RETURN user.name as user_name, user.file_path as user_file, labels(user)[0] as user_type
    """
}
