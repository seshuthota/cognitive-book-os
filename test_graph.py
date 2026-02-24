from src.cognitive_book_os.graph import build_graph_data
from src.cognitive_book_os.brain import Brain
import shutil
from pathlib import Path

# Create a mock brain
TEST_BRAIN = "test_brain_viz"
BRAINS_DIR = "brains"

path = Path(BRAINS_DIR) / TEST_BRAIN
if path.exists():
    shutil.rmtree(path)
path.mkdir(parents=True)

# Create some files
(path / "characters").mkdir()
(path / "characters/alice.md").write_text("""---
related: [characters/bob.md]
---
# Alice
""")
(path / "characters/bob.md").write_text("""---
related: []
---
# Bob
Links to [[characters/alice]]
""")

# Test
data = build_graph_data(TEST_BRAIN, BRAINS_DIR)

print(f"Nodes: {len(data['nodes'])}")
print(f"Links: {len(data['links'])}")

assert len(data['nodes']) == 2
# Alice -> Bob (related)
# Bob -> Alice (wiki-link)
assert len(data['links']) == 2

print("Graph logic verified!")

# Cleanup
shutil.rmtree(path)
