
import os
import sys

# Define Source Path relative to RAGaaS
# RAGaaS: /Users/dukekimm/Works/RAGaaS
# Doc2Onto: /Users/dukekimm/Works/Doc2Onto
src_base = os.path.abspath(os.path.join(os.getcwd(), '..', 'Doc2Onto'))

# Add to sys.path to resolve module
sys.path.append(src_base)

try:
    import doc2onto.qa.sparql_generator
    src_file = doc2onto.qa.sparql_generator.__file__
    print(f"Found source file at: {src_file}")
    
    with open(src_file, 'r') as f:
        content = f.read()
        
    dest_dir = os.path.join(os.getcwd(), 'backend/app/doc2onto/qa')
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    dest_file = os.path.join(dest_dir, 'sparql_generator.py')
    
    with open(dest_file, 'w') as f:
        f.write(content)
        
    print(f"Successfully copied content to: {dest_file}")
    print(f"Bytes written: {len(content)}")
    
except ImportError as e:
    print(f"ImportError: {e}")
    # Fallback: Try manual path construction if import fails 
    # (e.g. if dependencies like 'requests' are missing in this env for doc2onto)
    manual_path = os.path.join(src_base, 'doc2onto/qa/sparql_generator.py')
    if os.path.exists(manual_path):
        print(f"Trying manual read from: {manual_path}")
        with open(manual_path, 'r') as f:
            content = f.read()
        dest_file = os.path.join(os.getcwd(), 'backend/app/doc2onto/qa/sparql_generator.py')
        with open(dest_file, 'w') as f:
            f.write(content)
        print(f"Successfully copied via manual path to: {dest_file}")
    else:
        print(f"Manual path also failed: {manual_path}")

except Exception as e:
    print(f"Error: {e}")
