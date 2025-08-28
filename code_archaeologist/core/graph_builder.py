"""
Knowledge Graph Builder Module

Translates parsed AST data into a Neo4j knowledge graph, creating nodes and
relationships that represent the structure and dependencies of the codebase.
"""

import uuid
from typing import List, Dict, Optional, Set
from pathlib import Path

from neo4j import GraphDatabase, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

from ..models.schema import (
    CodeNode, CodeRelationship, NodeType, RelationshipType,
    GraphSchema
)
from .parser import ParsedFile, ParsedFunction, ParsedClass


class GraphBuilder:
    """Builds and manages the code knowledge graph in Neo4j."""
    
    def __init__(self, neo4j_uri: str = "bolt://localhost:7687", 
                 username: str = "neo4j", password: str = "password"):
        """Initialize the graph builder with Neo4j connection."""
        self.uri = neo4j_uri
        self.username = username
        self.password = password
        self.driver = None
        self._connect()
    
    def _connect(self):
        """Establish connection to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(
                self.uri, 
                auth=(self.username, self.password)
            )
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            print(f"Connected to Neo4j at {self.uri}")
        except (ServiceUnavailable, AuthError) as e:
            print(f"Failed to connect to Neo4j: {e}")
            print("Please ensure Neo4j is running and credentials are correct")
            self.driver = None
    
    def close(self):
        """Close the Neo4j connection."""
        if self.driver:
            self.driver.close()
    
    def initialize_schema(self):
        """Initialize the graph database schema with constraints and indexes."""
        if not self.driver:
            return False
        
        try:
            with self.driver.session() as session:
                # Create constraints
                for constraint in GraphSchema.get_cypher_create_constraints():
                    try:
                        session.run(constraint)
                    except Exception as e:
                        # Constraint might already exist
                        pass
                
                # Create indexes
                for index in GraphSchema.get_cypher_create_indexes():
                    try:
                        session.run(index)
                    except Exception as e:
                        # Index might already exist
                        pass
            
            print("Graph schema initialized")
            return True
        except Exception as e:
            print(f"Failed to initialize schema: {e}")
            return False
    
    def clear_graph(self):
        """Clear all nodes and relationships from the graph."""
        if not self.driver:
            return False
        
        try:
            with self.driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            print("Graph cleared")
            return True
        except Exception as e:
            print(f"Failed to clear graph: {e}")
            return False
    
    def build_graph_from_files(self, parsed_files: List[ParsedFile]) -> bool:
        """Build the complete knowledge graph from parsed files."""
        if not self.driver:
            return False
        
        print(f"Building graph from {len(parsed_files)} files...")
        
        # Track all nodes and relationships to create
        all_nodes: List[CodeNode] = []
        all_relationships: List[CodeRelationship] = []
        
        # First pass: Create all nodes
        for parsed_file in parsed_files:
            nodes, relationships = self._extract_nodes_and_relationships(parsed_file)
            all_nodes.extend(nodes)
            all_relationships.extend(relationships)
        
        # Create nodes in batches
        success = self._create_nodes_batch(all_nodes)
        if not success:
            return False
        
        # Create relationships in batches
        success = self._create_relationships_batch(all_relationships)
        if not success:
            return False
        
        print(f"Graph built: {len(all_nodes)} nodes, {len(all_relationships)} relationships")
        return True
    
    def _extract_nodes_and_relationships(self, parsed_file: ParsedFile) -> tuple[List[CodeNode], List[CodeRelationship]]:
        """Extract nodes and relationships from a parsed file."""
        nodes = []
        relationships = []
        
        # Create file node
        file_id = self._generate_id("file", parsed_file.file_path)
        file_node = CodeNode(
            id=file_id,
            type=NodeType.FILE,
            name=Path(parsed_file.file_path).name,
            file_path=parsed_file.file_path,
            properties={
                "language": parsed_file.language,
                "file_hash": parsed_file.file_hash
            }
        )
        nodes.append(file_node)
        
        # Create import nodes and relationships
        for import_stmt in parsed_file.imports:
            import_id = self._generate_id("import", import_stmt)
            import_node = CodeNode(
                id=import_id,
                type=NodeType.IMPORT,
                name=import_stmt,
                file_path=parsed_file.file_path,
                properties={"statement": import_stmt}
            )
            nodes.append(import_node)
            
            # File imports module
            relationships.append(CodeRelationship(
                source_id=file_id,
                target_id=import_id,
                type=RelationshipType.IMPORTS
            ))
        
        # Create global variable nodes
        for var_name in parsed_file.global_variables:
            var_id = self._generate_id("variable", f"{parsed_file.file_path}::{var_name}")
            var_node = CodeNode(
                id=var_id,
                type=NodeType.VARIABLE,
                name=var_name,
                file_path=parsed_file.file_path,
                properties={"scope": "global"}
            )
            nodes.append(var_node)
            
            # File defines variable
            relationships.append(CodeRelationship(
                source_id=file_id,
                target_id=var_id,
                type=RelationshipType.DEFINES
            ))
        
        # Create function nodes and relationships
        for function in parsed_file.functions:
            func_nodes, func_relationships = self._extract_function_nodes(
                function, parsed_file.file_path, file_id
            )
            nodes.extend(func_nodes)
            relationships.extend(func_relationships)
        
        # Create class nodes and relationships
        for class_def in parsed_file.classes:
            class_nodes, class_relationships = self._extract_class_nodes(
                class_def, parsed_file.file_path, file_id
            )
            nodes.extend(class_nodes)
            relationships.extend(class_relationships)
        
        return nodes, relationships
    
    def _extract_function_nodes(self, function: ParsedFunction, file_path: str, file_id: str) -> tuple[List[CodeNode], List[CodeRelationship]]:
        """Extract nodes and relationships for a function."""
        nodes = []
        relationships = []
        
        # Create function node
        func_id = self._generate_id("function", f"{file_path}::{function.name}")
        func_node = CodeNode(
            id=func_id,
            type=NodeType.FUNCTION,
            name=function.name,
            file_path=file_path,
            line_start=function.line_start,
            line_end=function.line_end,
            source_code=function.source_code,
            properties={
                "parameters": function.parameters,
                "return_type": function.return_type,
                "decorators": function.decorators
            }
        )
        nodes.append(func_node)
        
        # File contains function
        relationships.append(CodeRelationship(
            source_id=file_id,
            target_id=func_id,
            type=RelationshipType.CONTAINS
        ))
        
        # Create parameter nodes
        for param in function.parameters:
            param_id = self._generate_id("parameter", f"{func_id}::{param}")
            param_node = CodeNode(
                id=param_id,
                type=NodeType.PARAMETER,
                name=param,
                file_path=file_path,
                properties={"function": function.name}
            )
            nodes.append(param_node)
            
            # Function has parameter
            relationships.append(CodeRelationship(
                source_id=func_id,
                target_id=param_id,
                type=RelationshipType.HAS_PARAMETER
            ))
        
        # Create call relationships (will be resolved later)
        for called_func in function.calls:
            called_func_id = self._generate_id("function", f"*::{called_func}")
            relationships.append(CodeRelationship(
                source_id=func_id,
                target_id=called_func_id,
                type=RelationshipType.CALLS,
                properties={"unresolved": True}
            ))
        
        return nodes, relationships
    
    def _extract_class_nodes(self, class_def: ParsedClass, file_path: str, file_id: str) -> tuple[List[CodeNode], List[CodeRelationship]]:
        """Extract nodes and relationships for a class."""
        nodes = []
        relationships = []
        
        # Create class node
        class_id = self._generate_id("class", f"{file_path}::{class_def.name}")
        class_node = CodeNode(
            id=class_id,
            type=NodeType.CLASS,
            name=class_def.name,
            file_path=file_path,
            line_start=class_def.line_start,
            line_end=class_def.line_end,
            source_code=class_def.source_code,
            properties={
                "base_classes": class_def.base_classes,
                "attributes": class_def.attributes,
                "decorators": class_def.decorators
            }
        )
        nodes.append(class_node)
        
        # File contains class
        relationships.append(CodeRelationship(
            source_id=file_id,
            target_id=class_id,
            type=RelationshipType.CONTAINS
        ))
        
        # Create inheritance relationships
        for base_class in class_def.base_classes:
            base_class_id = self._generate_id("class", f"*::{base_class}")
            relationships.append(CodeRelationship(
                source_id=class_id,
                target_id=base_class_id,
                type=RelationshipType.INHERITS_FROM,
                properties={"unresolved": True}
            ))
        
        # Create method nodes
        for method in class_def.methods:
            method_nodes, method_relationships = self._extract_function_nodes(
                method, file_path, file_id
            )
            nodes.extend(method_nodes)
            relationships.extend(method_relationships)
            
            # Class contains method
            method_id = self._generate_id("function", f"{file_path}::{method.name}")
            relationships.append(CodeRelationship(
                source_id=class_id,
                target_id=method_id,
                type=RelationshipType.CONTAINS
            ))
        
        return nodes, relationships
    
    def _generate_id(self, node_type: str, identifier: str) -> str:
        """Generate a unique ID for a node."""
        import hashlib
        # Use SHA-256 hash for better uniqueness
        hash_object = hashlib.sha256(f"{node_type}:{identifier}".encode())
        hash_hex = hash_object.hexdigest()
        return f"{node_type}:{hash_hex[:16]}"
    
    def _create_nodes_batch(self, nodes: List[CodeNode]) -> bool:
        """Create nodes in batches for better performance."""
        if not nodes:
            return True
        
        successful_nodes = 0
        try:
            with self.driver.session() as session:
                # Process nodes individually to avoid transaction rollbacks
                for i, node in enumerate(nodes):
                    try:
                        # Use MERGE instead of CREATE to handle duplicates gracefully
                        cypher, properties = GraphSchema.node_to_cypher(node)
                        # Convert CREATE to MERGE to avoid constraint violations
                        if cypher.startswith("CREATE "):
                            cypher = cypher.replace("CREATE ", "MERGE ", 1)
                        
                        session.run(cypher, properties)
                        successful_nodes += 1
                        
                        # Progress update every 100 nodes
                        if (i + 1) % 100 == 0:
                            print(f"Created {i + 1}/{len(nodes)} nodes")
                            
                    except Exception as e:
                        # Skip nodes that fail but continue processing
                        if "already exists" not in str(e).lower():
                            print(f"Warning: Failed to create node {node.id}: {e}")
                        continue
                
                print(f"Successfully created {successful_nodes}/{len(nodes)} nodes")
            
            return True
        except Exception as e:
            print(f"Failed to create nodes: {e}")
            return False
    
    def _create_relationships_batch(self, relationships: List[CodeRelationship]) -> bool:
        """Create relationships in batches for better performance."""
        if not relationships:
            return True
        
        successful_relationships = 0
        try:
            with self.driver.session() as session:
                # Process relationships individually to avoid transaction rollbacks
                for i, rel in enumerate(relationships):
                    # Skip unresolved relationships for now
                    if rel.properties.get("unresolved"):
                        continue
                    
                    try:
                        cypher, properties = GraphSchema.relationship_to_cypher(rel)
                        # Convert CREATE to MERGE for relationships too
                        if "CREATE " in cypher:
                            cypher = cypher.replace("CREATE ", "MERGE ", 1)
                        
                        session.run(cypher, properties)
                        successful_relationships += 1
                        
                        # Progress update every 100 relationships
                        if (i + 1) % 100 == 0:
                            print(f"Created {i + 1}/{len(relationships)} relationships")
                            
                    except Exception as e:
                        # Skip relationships that fail but continue processing
                        if "already exists" not in str(e).lower() and "not exist" not in str(e).lower():
                            print(f"Warning: Failed to create relationship {rel.from_id} -> {rel.to_id}: {e}")
                        continue
                
                print(f"Successfully created {successful_relationships}/{len(relationships)} relationships")
            
            return True
        except Exception as e:
            print(f"Failed to create relationships: {e}")
            return False
    
    def get_graph_stats(self) -> Dict:
        """Get statistics about the knowledge graph."""
        if not self.driver:
            return {}
        
        try:
            with self.driver.session() as session:
                # Count nodes by type
                node_counts = {}
                for node_type in NodeType:
                    result = session.run(f"MATCH (n:{node_type.value}) RETURN count(n) as count")
                    node_counts[node_type.value] = result.single()["count"]
                
                # Count relationships by type
                rel_counts = {}
                for rel_type in RelationshipType:
                    result = session.run(f"MATCH ()-[r:{rel_type.value}]->() RETURN count(r) as count")
                    rel_counts[rel_type.value] = result.single()["count"]
                
                return {
                    "nodes": node_counts,
                    "relationships": rel_counts,
                    "total_nodes": sum(node_counts.values()),
                    "total_relationships": sum(rel_counts.values())
                }
        except Exception as e:
            print(f"Failed to get graph stats: {e}")
            return {}
    
    def query_graph(self, cypher_query: str, parameters: Dict = None) -> List[Dict]:
        """Execute a Cypher query against the graph."""
        if not self.driver:
            return []
        
        try:
            with self.driver.session() as session:
                result = session.run(cypher_query, parameters or {})
                return [record.data() for record in result]
        except Exception as e:
            print(f"Query failed: {e}")
            return []
