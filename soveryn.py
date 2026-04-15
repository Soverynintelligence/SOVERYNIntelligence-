import sys
from pathlib import Path
from crew_setup import chat_with_agent


def main():
    if len(sys.argv) < 3:
        print("Usage: python soveryn.py <agent> <message> [image_path]")
        print("Agents: charlie, vett, tinker")
        return
    
    agent_name = sys.argv[1].lower()
    message = sys.argv[2]
    image_path = sys.argv[3] if len(sys.argv) > 3 else None
    
    if agent_name not in ["charlie", "vett", "tinker"]:
        print(f"Unknown agent: {agent_name}")
        return
    
    if image_path and not Path(image_path).exists():
        print(f"Error: Image not found: {image_path}")
        return
    
    print(f"\nTalking to {agent_name.title()}...\n")
    
    result = chat_with_agent(agent_name, message, image_path)
    print(f"\n{agent_name.title()}: {result}\n")


if __name__ == "__main__":
    main()
