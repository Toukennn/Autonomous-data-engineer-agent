from agents.data_engineer import data_engineer
from langchain_core.messages import HumanMessage


if __name__ == "__main__":
    response = data_engineer.invoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Extract the first page of Pokémon data from "
                        "https://pokeapi.co/api/v2/pokemon?limit=20&offset=0 "
                        "into a CSV dataset named pokemon. "
                        "Then create a Silver dataset named pokemon_clean "
                        "by stripping and lowercasing the name column and "
                        "keeping only name and url. "
                        "Then create a Gold dataset named pokemon_saur "
                        "containing only Pokémon whose name contains 'saur', "
                        "keeping name and url."
                    )
                )
            ]
        }
    )

    print(
        response["messages"][-1].content
    )