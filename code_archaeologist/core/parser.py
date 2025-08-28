"""
AST Parser Module

Uses tree-sitter to parse source code files into Abstract Syntax Trees (ASTs)
and extract structural information for knowledge graph construction.
"""

import os
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass

from tree_sitter import Language, Parser, Node
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_java as tsjava
import tree_sitter_cpp as tscpp
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust
import tree_sitter_typescript as tstypescript

from ..models.schema import CodeNode, CodeRelationship, NodeType, RelationshipType


@dataclass
class ParsedFunction:
    """Represents a parsed function with its metadata."""
    name: str
    parameters: List[str]
    return_type: Optional[str]
    line_start: int
    line_end: int
    source_code: str
    calls: List[str]
    variables_used: List[str]
    decorators: List[str]


@dataclass
class ParsedClass:
    """Represents a parsed class with its metadata."""
    name: str
    base_classes: List[str]
    methods: List[ParsedFunction]
    attributes: List[str]
    line_start: int
    line_end: int
    source_code: str
    decorators: List[str]


@dataclass
class ParsedFile:
    """Represents a parsed file with all its components."""
    file_path: str
    language: str
    imports: List[str]
    functions: List[ParsedFunction]
    classes: List[ParsedClass]
    global_variables: List[str]
    file_hash: str


class MultiLanguageParser:
    """Multi-language AST parser using tree-sitter."""
    
    # Language mappings - will be initialized in __init__
    LANGUAGE_MAP = {}
    
    def __init__(self):
        """Initialize the multi-language parser."""
        self.parsers: Dict[str, Parser] = {}
        self._initialize_language_map()
        self._setup_parsers()
    
    def _initialize_language_map(self):
        """Initialize language mappings with error handling for different tree-sitter versions."""
        language_configs = [
            ('.py', 'python', tspython),
            ('.js', 'javascript', tsjavascript),
            ('.ts', 'typescript', tstypescript),
            ('.tsx', 'typescript', tstypescript),
            ('.java', 'java', tsjava),
            ('.cpp', 'cpp', tscpp),
            ('.cc', 'cpp', tscpp),
            ('.cxx', 'cpp', tscpp),
            ('.c', 'cpp', tscpp),
            ('.h', 'cpp', tscpp),
            ('.hpp', 'cpp', tscpp),
            ('.go', 'go', tsgo),
            ('.rs', 'rust', tsrust),
        ]
        
        for ext, lang_name, module in language_configs:
            try:
                # Try different ways to get the language based on tree-sitter version
                language = None
                
                if hasattr(module, 'language'):
                    if callable(module.language):
                        # Get the raw language object
                        raw_language = module.language()
                        # Try to wrap it in Language if needed
                        try:
                            language = Language(raw_language)
                        except:
                            # If wrapping fails, use the raw language
                            language = raw_language
                    else:
                        language = module.language
                elif hasattr(module, 'LANGUAGE'):
                    language = module.LANGUAGE
                
                if language is None:
                    print(f"Warning: Could not initialize {lang_name} parser")
                    continue
                
                self.LANGUAGE_MAP[ext] = (lang_name, language)
            except Exception as e:
                print(f"Warning: Failed to initialize {lang_name} parser: {e}")
                continue
    
    def _setup_parsers(self):
        """Set up parsers for each supported language."""
        for ext, (lang_name, language) in self.LANGUAGE_MAP.items():
            if lang_name not in self.parsers:
                parser = Parser()
                try:
                    # Try the newer API first
                    if hasattr(parser, 'language'):
                        parser.language = language
                    elif hasattr(parser, 'set_language'):
                        parser.set_language(language)
                    else:
                        print(f"Warning: Could not set language for {lang_name} parser")
                        continue
                    self.parsers[lang_name] = parser
                except Exception as e:
                    print(f"Warning: Failed to setup {lang_name} parser: {e}")
                    continue
    
    def get_supported_extensions(self) -> Set[str]:
        """Get all supported file extensions."""
        return set(self.LANGUAGE_MAP.keys())
    
    def parse_file(self, file_path: str) -> Optional[ParsedFile]:
        """Parse a single file and extract its structure."""
        path = Path(file_path)
        
        if not path.exists():
            return None
        
        extension = path.suffix.lower()
        if extension not in self.LANGUAGE_MAP:
            return None
        
        lang_name, _ = self.LANGUAGE_MAP[extension]
        parser = self.parsers[lang_name]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
        except (UnicodeDecodeError, IOError):
            return None
        
        # Calculate file hash for change detection
        file_hash = hashlib.md5(source_code.encode()).hexdigest()
        
        # Parse the source code
        tree = parser.parse(bytes(source_code, 'utf8'))
        
        # Extract components based on language
        if lang_name == 'python':
            return self._parse_python_file(file_path, source_code, tree.root_node, file_hash)
        elif lang_name in ['javascript', 'typescript']:
            return self._parse_javascript_file(file_path, source_code, tree.root_node, file_hash, lang_name)
        elif lang_name == 'java':
            return self._parse_java_file(file_path, source_code, tree.root_node, file_hash)
        else:
            # Generic parsing for other languages
            return self._parse_generic_file(file_path, source_code, tree.root_node, file_hash, lang_name)
    
    def _parse_python_file(self, file_path: str, source_code: str, root_node: Node, file_hash: str) -> ParsedFile:
        """Parse a Python file specifically."""
        imports = []
        functions = []
        classes = []
        global_variables = []
        
        def extract_text(node: Node) -> str:
            return source_code[node.start_byte:node.end_byte]
        
        def visit_node(node: Node):
            if node.type == 'import_statement' or node.type == 'import_from_statement':
                imports.append(extract_text(node).strip())
            
            elif node.type == 'function_definition':
                func = self._parse_python_function(node, source_code)
                if func:
                    functions.append(func)
            
            elif node.type == 'class_definition':
                cls = self._parse_python_class(node, source_code)
                if cls:
                    classes.append(cls)
            
            elif node.type == 'assignment' and node.parent and node.parent.type == 'module':
                # Global variable assignment
                for child in node.children:
                    if child.type == 'identifier':
                        global_variables.append(extract_text(child))
            
            # Recursively visit children
            for child in node.children:
                visit_node(child)
        
        visit_node(root_node)
        
        return ParsedFile(
            file_path=file_path,
            language='python',
            imports=imports,
            functions=functions,
            classes=classes,
            global_variables=global_variables,
            file_hash=file_hash
        )
    
    def _parse_python_function(self, node: Node, source_code: str) -> Optional[ParsedFunction]:
        """Parse a Python function definition."""
        name = None
        parameters = []
        return_type = None
        calls = []
        variables_used = []
        decorators = []
        
        def extract_text(n: Node) -> str:
            return source_code[n.start_byte:n.end_byte]
        
        # Find function name
        for child in node.children:
            if child.type == 'identifier':
                name = extract_text(child)
                break
        
        if not name:
            return None
        
        # Find parameters
        for child in node.children:
            if child.type == 'parameters':
                for param_child in child.children:
                    if param_child.type == 'identifier':
                        parameters.append(extract_text(param_child))
        
        # Find decorators (look at previous siblings)
        if node.prev_sibling and node.prev_sibling.type == 'decorated_definition':
            for decorator_node in node.prev_sibling.children:
                if decorator_node.type == 'decorator':
                    decorators.append(extract_text(decorator_node))
        
        # Find function calls and variable usage in function body
        def find_calls_and_vars(n: Node):
            if n.type == 'call':
                # Find the function being called
                for child in n.children:
                    if child.type == 'identifier':
                        calls.append(extract_text(child))
                    elif child.type == 'attribute':
                        calls.append(extract_text(child))
            elif n.type == 'identifier':
                var_name = extract_text(n)
                if var_name not in parameters and var_name != name:
                    variables_used.append(var_name)
            
            for child in n.children:
                find_calls_and_vars(child)
        
        # Find function body
        for child in node.children:
            if child.type == 'block':
                find_calls_and_vars(child)
        
        return ParsedFunction(
            name=name,
            parameters=parameters,
            return_type=return_type,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            source_code=extract_text(node),
            calls=list(set(calls)),  # Remove duplicates
            variables_used=list(set(variables_used)),
            decorators=decorators
        )
    
    def _parse_python_class(self, node: Node, source_code: str) -> Optional[ParsedClass]:
        """Parse a Python class definition."""
        name = None
        base_classes = []
        methods = []
        attributes = []
        decorators = []
        
        def extract_text(n: Node) -> str:
            return source_code[n.start_byte:n.end_byte]
        
        # Find class name
        for child in node.children:
            if child.type == 'identifier':
                name = extract_text(child)
                break
        
        if not name:
            return None
        
        # Find base classes
        for child in node.children:
            if child.type == 'argument_list':
                for arg_child in child.children:
                    if arg_child.type == 'identifier':
                        base_classes.append(extract_text(arg_child))
        
        # Find methods and attributes
        def visit_class_body(n: Node):
            if n.type == 'function_definition':
                method = self._parse_python_function(n, source_code)
                if method:
                    methods.append(method)
            elif n.type == 'assignment':
                # Class attribute
                for child in n.children:
                    if child.type == 'identifier':
                        attributes.append(extract_text(child))
            
            for child in n.children:
                visit_class_body(child)
        
        # Find class body
        for child in node.children:
            if child.type == 'block':
                visit_class_body(child)
        
        return ParsedClass(
            name=name,
            base_classes=base_classes,
            methods=methods,
            attributes=attributes,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            source_code=extract_text(node),
            decorators=decorators
        )
    
    def _parse_javascript_file(self, file_path: str, source_code: str, root_node: Node, file_hash: str, lang_name: str) -> ParsedFile:
        """Parse a JavaScript/TypeScript file."""
        imports = []
        functions = []
        classes = []
        global_variables = []
        
        def extract_text(node: Node) -> str:
            return source_code[node.start_byte:node.end_byte]
        
        def visit_node(node: Node):
            if node.type in ['import_statement', 'import_clause']:
                imports.append(extract_text(node).strip())
            elif node.type in ['function_declaration', 'function_expression', 'arrow_function']:
                func = self._parse_js_function(node, source_code)
                if func:
                    functions.append(func)
            elif node.type == 'class_declaration':
                cls = self._parse_js_class(node, source_code)
                if cls:
                    classes.append(cls)
            elif node.type == 'variable_declaration':
                for child in node.children:
                    if child.type == 'variable_declarator':
                        for var_child in child.children:
                            if var_child.type == 'identifier':
                                global_variables.append(extract_text(var_child))
            
            for child in node.children:
                visit_node(child)
        
        visit_node(root_node)
        
        return ParsedFile(
            file_path=file_path,
            language=lang_name,
            imports=imports,
            functions=functions,
            classes=classes,
            global_variables=global_variables,
            file_hash=file_hash
        )
    
    def _parse_js_function(self, node: Node, source_code: str) -> Optional[ParsedFunction]:
        """Parse a JavaScript/TypeScript function."""
        name = "anonymous"
        parameters = []
        calls = []
        variables_used = []
        
        def extract_text(n: Node) -> str:
            return source_code[n.start_byte:n.end_byte]
        
        # Find function name
        for child in node.children:
            if child.type == 'identifier':
                name = extract_text(child)
                break
        
        # Find parameters
        for child in node.children:
            if child.type == 'formal_parameters':
                for param_child in child.children:
                    if param_child.type == 'identifier':
                        parameters.append(extract_text(param_child))
        
        return ParsedFunction(
            name=name,
            parameters=parameters,
            return_type=None,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            source_code=extract_text(node),
            calls=calls,
            variables_used=variables_used,
            decorators=[]
        )
    
    def _parse_js_class(self, node: Node, source_code: str) -> Optional[ParsedClass]:
        """Parse a JavaScript/TypeScript class."""
        name = None
        base_classes = []
        methods = []
        
        def extract_text(n: Node) -> str:
            return source_code[n.start_byte:n.end_byte]
        
        # Find class name
        for child in node.children:
            if child.type == 'identifier':
                name = extract_text(child)
                break
        
        if not name:
            return None
        
        return ParsedClass(
            name=name,
            base_classes=base_classes,
            methods=methods,
            attributes=[],
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            source_code=extract_text(node),
            decorators=[]
        )
    
    def _parse_java_file(self, file_path: str, source_code: str, root_node: Node, file_hash: str) -> ParsedFile:
        """Parse a Java file."""
        # Simplified Java parsing - can be expanded
        return ParsedFile(
            file_path=file_path,
            language='java',
            imports=[],
            functions=[],
            classes=[],
            global_variables=[],
            file_hash=file_hash
        )
    
    def _parse_generic_file(self, file_path: str, source_code: str, root_node: Node, file_hash: str, lang_name: str) -> ParsedFile:
        """Generic parsing for unsupported languages."""
        return ParsedFile(
            file_path=file_path,
            language=lang_name,
            imports=[],
            functions=[],
            classes=[],
            global_variables=[],
            file_hash=file_hash
        )
    
    def parse_repository(self, repo_path: str, exclude_patterns: Optional[List[str]] = None) -> List[ParsedFile]:
        """Parse all supported files in a repository."""
        if exclude_patterns is None:
            exclude_patterns = [
                '*/node_modules/*',
                '*/__pycache__/*',
                '*/venv/*',
                '*/env/*',
                '*/.git/*',
                '*/build/*',
                '*/dist/*',
                '*/target/*',
                '*.min.js',
                '*.bundle.js'
            ]
        
        parsed_files = []
        repo_path = Path(repo_path)
        
        if not repo_path.exists():
            return parsed_files
        
        supported_extensions = self.get_supported_extensions()
        
        for file_path in repo_path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                # Check exclude patterns
                should_exclude = False
                for pattern in exclude_patterns:
                    if file_path.match(pattern):
                        should_exclude = True
                        break
                
                if not should_exclude:
                    parsed_file = self.parse_file(str(file_path))
                    if parsed_file:
                        parsed_files.append(parsed_file)
        
        return parsed_files
