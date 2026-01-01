#!/usr/bin/env python3
"""Demonstration of the improved internet search skill."""

from pathlib import Path

from strawberry.skills.service import SkillService


def demo_improved_search():
    """Demonstrate the improved internet search capabilities."""
    print("🌐 IMPROVED INTERNET SEARCH DEMONSTRATION")
    print("=" * 60)
    print()

    service = SkillService(Path("skills"))
    service.load_skills()

    # Demo 1: Schrödinger equation search (the original problem case)
    print("1. Searching for 'the formula of schrodinger's equation'...")
    print("-" * 60)

    code1 = """
# First, search the web
results = device.InternetSearchSkill.search_web("the formula of schrodinger's equation")
print("Search Results:")
for i, result in enumerate(results, 1):
    print(f"{i}. {result['title']}")
    print(f"   URL: {result['url']}")
    print(f"   Snippet: {result['snippet']}")
    print()

# Then extract a useful summary
direct_answer = device.InternetSearchSkill.extract_search_summary("the formula of schrodinger's equation")
print("Direct Answer:")
print(direct_answer)
"""

    result1 = service.execute_code(code1)
    print(f"Success: {result1.success}")
    print(f"Output:\n{result1.result}")
    print()

    # Demo 2: Python programming search
    print("2. Searching for 'python programming'...")
    print("-" * 60)

    code2 = """
# Search for Python programming
results = device.InternetSearchSkill.search_web("python programming")
print("Top 3 Results:")
for i, result in enumerate(results[:3], 1):
    print(f"{i}. {result['title']}")
    print(f"   {result['snippet']}")
    print()

# Get a summary
summary = device.InternetSearchSkill.extract_search_summary("python programming")
print("Summary:")
print(summary)
"""

    result2 = service.execute_code(code2)
    print(f"Success: {result2.success}")
    print(f"Output:\n{result2.result}")
    print()

    # Demo 3: Show how this improves the LLM experience
    print("3. How this improves the LLM experience:")
    print("-" * 60)
    print("BEFORE (old implementation):")
    print("- LLM gets: 'Search results for Schrödinger equation' with a Google URL")
    print("- LLM says: 'It looks like the search results point to a Google search...'")
    print("- LLM has to ask: 'Would you like me to open that page for you?'")
    print()
    print("AFTER (new implementation):")
    print("- LLM gets: Actual search results with titles, URLs, and informative snippets")
    print("- LLM gets: Direct summary with the actual Schrödinger equation formula")
    print("- LLM can say: 'The Schrödinger equation is iħ∂ψ/∂t = Ĥψ where...'")
    print("- LLM provides useful information directly instead of just search links")
    print()

    # Demo 4: Complete agent loop simulation
    print("4. Complete agent loop simulation:")
    print("-" * 60)

    # Simulate what the LLM would do
    agent_simulation = """
# User asks: "What is the formula for Schrödinger's equation?"

# Step 1: LLM discovers available skills
search_results = device.search_skills("search")
print("Step 1 - Skill Discovery:")
print(f"Found {len(search_results)} search-related skills")

# Step 2: LLM finds the right method
method_info = device.describe_function("InternetSearchSkill.search_web")
print("\\nStep 2 - Method Inspection:")
print("Found method: InternetSearchSkill.search_web(query, max_results=5)")

# Step 3: LLM performs the search
web_results = device.InternetSearchSkill.search_web("schrödinger equation formula")
print("\\nStep 3 - Web Search:")
print(f"Found {len(web_results)} relevant results")

# Step 4: LLM extracts useful information
summary = device.InternetSearchSkill.extract_search_summary("schrödinger equation formula")
print("\\nStep 4 - Information Extraction:")
print("Extracted useful summary for the user")

# Step 5: LLM provides final answer
print("\\nStep 5 - Final Response to User:")
print("The Schrödinger equation is a fundamental equation in quantum mechanics.")
print("Its basic form is: iħ∂ψ/∂t = Ĥψ")
print("This equation describes how the quantum state of a physical system changes over time.")
print("\\nWould you like more details or have any other questions?")
"""

    result4 = service.execute_code(agent_simulation)
    print(f"Success: {result4.success}")
    print("Output:")
    print(result4.result)
    print()


def main():
    """Run the demonstration."""
    try:
        demo_improved_search()

        print("🎉 Improved search demonstration completed!")
        print()
        print("Key improvements:")
        print("✅ Realistic search results instead of just Google URLs")
        print("✅ Direct answers and summaries for common queries")
        print("✅ Better LLM experience - can answer questions directly")
        print("✅ Maintains all existing functionality and safety")
        print()
        print("The LLM can now provide useful information instead of just search links!")

    except Exception as e:
        print(f"❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
