"""
GraphRAG Query Engine Module

The intelligent core that uses LLMs for query planning, Cypher generation,
and synthesis of structured code information into natural language answers.
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from ..models.schema import QUERY_TEMPLATES, NodeType, RelationshipType
from .graph_builder import GraphBuilder


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    GEMINI = "gemini"


@dataclass
class QueryPlan:
    """Represents a multi-step query execution plan."""
    steps: List[Dict[str, Any]]
    original_query: str
    estimated_complexity: str


@dataclass
class QueryResult:
    """Represents the result of a GraphRAG query."""
    answer: str
    cypher_queries: List[str]
    raw_data: List[Dict]
    execution_time: float
    plan: QueryPlan


class GraphRAGQueryEngine:
    """GraphRAG query engine that combines LLMs with graph database queries."""
    
    def __init__(self, graph_builder: GraphBuilder, 
                 llm_provider: LLMProvider = LLMProvider.GEMINI,
                 api_key: Optional[str] = None,
                 model_name: Optional[str] = None):
        """Initialize the query engine."""
        self.graph_builder = graph_builder
        self.llm_provider = llm_provider
        self.api_key = api_key
        
        # Set default models
        if model_name is None:
            self.model_name = "gemini-1.5-flash"
        else:
            self.model_name = model_name
        
        # Initialize LLM client
        self._initialize_llm_client()
        
        # Graph schema for LLM context
        self.schema_context = self._build_schema_context()
    
    def _initialize_llm_client(self):
        """Initialize the LLM client based on provider."""
        if self.llm_provider == LLMProvider.GEMINI and GEMINI_AVAILABLE:
            if self.api_key:
                genai.configure(api_key=self.api_key)
            self.llm_client = genai
        else:
            print(f"LLM provider {self.llm_provider} not available or not installed")
            self.llm_client = None
    
    def _build_schema_context(self) -> str:
        """Build a context string describing the graph schema."""
        context = """
# Code Knowledge Graph Schema

## Node Types:
"""
        for node_type in NodeType:
            context += f"- {node_type.value}: Represents {node_type.value.lower()}s in the codebase\n"
        
        context += "\n## Relationship Types:\n"
        for rel_type in RelationshipType:
            context += f"- {rel_type.value}: {self._get_relationship_description(rel_type)}\n"
        
        context += """
## Common Query Patterns:
- Find functions: MATCH (f:Function {name: $name}) RETURN f
- Find function calls: MATCH (f:Function)-[:CALLS]->(called:Function) RETURN f, called
- Find class methods: MATCH (c:Class)-[:CONTAINS]->(m:Function) RETURN c, m
- Trace dependencies: MATCH (f:Function)-[:CALLS*1..3]->(dep) RETURN f, dep
- Find inheritance: MATCH (c:Class)-[:INHERITS_FROM]->(parent:Class) RETURN c, parent
"""
        return context
    
    def _get_relationship_description(self, rel_type: RelationshipType) -> str:
        """Get a human-readable description of a relationship type."""
        descriptions = {
            RelationshipType.CONTAINS: "A container (file/class) contains another element",
            RelationshipType.IMPORTS: "A file imports a module or library",
            RelationshipType.DEFINES: "A scope defines a variable or function",
            RelationshipType.CALLS: "A function calls another function",
            RelationshipType.INHERITS_FROM: "A class inherits from another class",
            RelationshipType.INSTANTIATES: "Code creates an instance of a class",
            RelationshipType.USES: "Code uses a variable or resource",
            RelationshipType.RETURNS: "A function returns a specific type",
            RelationshipType.HAS_PARAMETER: "A function has a parameter",
            RelationshipType.REFERENCES: "Code references another element",
            RelationshipType.DECORATES: "A decorator decorates a function or class"
        }
        return descriptions.get(rel_type, "Relationship between code elements")
    
    async def query(self, user_query: str) -> QueryResult:
        """Execute a complete GraphRAG query."""
        import time
        start_time = time.time()
        
        # Step 1: Generate query plan
        plan = await self._generate_query_plan(user_query)
        
        # Step 2: Execute query steps
        all_cypher_queries = []
        all_raw_data = []
        
        for step in plan.steps:
            if step["type"] == "graph_query":
                cypher_query = await self._generate_cypher_query(step["description"])
                if cypher_query:
                    all_cypher_queries.append(cypher_query)
                    raw_data = self.graph_builder.query_graph(cypher_query)
                    all_raw_data.extend(raw_data)
        
        # Step 3: Synthesize final answer
        answer = await self._synthesize_answer(user_query, all_raw_data, plan)
        
        execution_time = time.time() - start_time
        
        return QueryResult(
            answer=answer,
            cypher_queries=all_cypher_queries,
            raw_data=all_raw_data,
            execution_time=execution_time,
            plan=plan
        )
    
    async def _generate_query_plan(self, user_query: str) -> QueryPlan:
        """Generate a multi-step execution plan for the user query."""
        system_prompt = """You are a query planner for a code analysis system. Given a user's natural language query about a codebase, create a step-by-step execution plan.

Each step should be one of these types:
1. "graph_query" - Query the knowledge graph for specific information
2. "synthesis" - Combine and analyze retrieved information

Return your plan as a JSON object with this structure:
{
    "steps": [
        {
            "type": "graph_query",
            "description": "Find the definition of function X",
            "priority": 1
        }
    ],
    "estimated_complexity": "simple|medium|complex"
}

Focus on breaking down complex queries into simpler graph queries that can be executed efficiently."""
        
        user_prompt = f"""
User Query: "{user_query}"

Available graph schema:
{self.schema_context}

Create an execution plan for this query.
"""
        
        try:
            response = await self._call_llm(system_prompt, user_prompt)
            plan_data = json.loads(response)
            
            return QueryPlan(
                steps=plan_data.get("steps", []),
                original_query=user_query,
                estimated_complexity=plan_data.get("estimated_complexity", "medium")
            )
        except Exception as e:
            print(f"Failed to generate query plan: {e}")
            # Fallback to simple plan
            return QueryPlan(
                steps=[{
                    "type": "graph_query",
                    "description": f"Find information related to: {user_query}",
                    "priority": 1
                }],
                original_query=user_query,
                estimated_complexity="simple"
            )
    
    async def _generate_cypher_query(self, query_description: str) -> Optional[str]:
        """Generate a Cypher query from a natural language description."""
        system_prompt = f"""You are a Cypher query generator for a code knowledge graph. Given a description of what information to find, generate an efficient Cypher query.

Graph Schema:
{self.schema_context}

Rules:
1. Always use parameterized queries when possible
2. Limit results to avoid overwhelming output (use LIMIT)
3. Return relevant node properties and relationships
4. Use OPTIONAL MATCH for optional relationships
5. Only return valid Cypher syntax

Common patterns you can use:
{chr(10).join([f"-- {name}:{chr(10)}{query}" for name, query in QUERY_TEMPLATES.items()])}
"""
        
        user_prompt = f"""
Generate a Cypher query for: "{query_description}"

Return only the Cypher query, no explanation.
"""
        
        try:
            cypher_query = await self._call_llm(system_prompt, user_prompt)
            # Clean up the response
            cypher_query = cypher_query.strip()
            if cypher_query.startswith("```"):
                cypher_query = re.sub(r"```(?:cypher)?\n?", "", cypher_query)
                cypher_query = cypher_query.strip("```")
            
            return cypher_query
        except Exception as e:
            print(f"Failed to generate Cypher query: {e}")
            return None
    
    async def _synthesize_answer(self, original_query: str, raw_data: List[Dict], plan: QueryPlan) -> str:
        """Synthesize the final answer from retrieved graph data."""
        if not raw_data:
            return "I couldn't find any relevant information in the codebase for your query."
        
        system_prompt = """You are a code analysis assistant. Given structured data retrieved from a code knowledge graph, provide a clear, comprehensive answer to the user's question.

Guidelines:
1. Be specific and accurate - only use information from the provided data
2. Include relevant code snippets when helpful
3. Explain relationships and dependencies clearly
4. Use proper formatting (markdown) for code and structure
5. If the data is incomplete, acknowledge limitations
6. Focus on practical insights for developers"""
        
        # Prepare context from raw data
        context_parts = []
        for i, item in enumerate(raw_data[:20]):  # Limit context size
            context_parts.append(f"Data {i+1}: {json.dumps(item, indent=2)}")
        
        context = "\n\n".join(context_parts)
        
        user_prompt = f"""
Original Query: "{original_query}"

Retrieved Data:
{context}

Please provide a comprehensive answer to the user's query based on this data.
"""
        
        try:
            answer = await self._call_llm(system_prompt, user_prompt)
            return answer
        except Exception as e:
            print(f"Failed to synthesize answer: {e}")
            return f"I found {len(raw_data)} relevant items in the codebase, but encountered an error while generating the response."
    
    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the configured LLM with the given prompts."""
        if not self.llm_client:
            raise Exception("LLM client not initialized")
        
        if self.llm_provider == LLMProvider.GEMINI:
            response = await self._call_gemini(system_prompt, user_prompt)
        else:
            raise Exception(f"Unsupported LLM provider: {self.llm_provider}")
        
        return response
    
    async def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        """Call Google Gemini API."""
        try:
            model = self.llm_client.GenerativeModel(self.model_name)
            
            # Combine system and user prompts for Gemini
            combined_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
            
            response = await model.generate_content_async(
                combined_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                )
            )
            return response.text
        except Exception as e:
            # Fallback to sync call if async fails
            model = self.llm_client.GenerativeModel(self.model_name)
            combined_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
            
            response = model.generate_content(
                combined_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                )
            )
            return response.text
    
    def get_query_suggestions(self, codebase_stats: Dict) -> List[str]:
        """Generate query suggestions based on codebase statistics."""
        suggestions = []
        
        # Basic suggestions
        suggestions.extend([
            "What are the main classes in this codebase?",
            "Show me the most complex functions (with the most dependencies)",
            "What functions are called most frequently?",
            "Find all deprecated functions and where they're used"
        ])
        
        # Dynamic suggestions based on stats
        if codebase_stats.get("nodes", {}).get("Class", 0) > 0:
            suggestions.append("Show me the inheritance hierarchy of classes")
        
        if codebase_stats.get("nodes", {}).get("Function", 0) > 10:
            suggestions.append("Find functions that are never called (potential dead code)")
        
        if codebase_stats.get("relationships", {}).get("IMPORTS", 0) > 0:
            suggestions.append("What external libraries does this codebase depend on?")
        
        return suggestions[:8]  # Limit to 8 suggestions
