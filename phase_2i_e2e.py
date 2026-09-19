from langchain_core.messages import (
    HumanMessage,
)

from agents.data_engineer import (
    data_engineer,
)


# ============================================================
# PHASE 2I — FULL E2E
# ============================================================


def run_etl():
    """
    Real:
        API
          ↓
        Bronze filesystem
          ↓
        PostgreSQL Bronze
          ↓
        dbt Silver
          ↓
        dbt Gold
    """

    request = """

Build a warehouse-backed PostgreSQL + dbt pipeline.

Extract only the first page of book-search results from:

https://openlibrary.org/search.json?q=machine%20learning&fields=key,title,first_publish_year,edition_count&limit=20&page=1

Do not paginate.

The API records are located under the top-level field:

docs

Save the Bronze dataset as:

books_phase2i

Then create a dbt Silver dataset named:

books_phase2i_clean

For Silver:
- keep only key, title, first_publish_year, and edition_count
- remove rows where title is null
- remove rows where first_publish_year is null
- cast first_publish_year to integer
- cast edition_count to integer

Then create a dbt Gold dataset named:

books_phase2i_modern

For Gold:
- keep books whose first_publish_year is greater than or equal to 2000
- keep books whose edition_count is greater than or equal to 5
- keep only title, first_publish_year, and edition_count
"""

    response = (
        data_engineer.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=request
                    )
                ]
            }
        )
    )

    final_message = (
        response["messages"][-1]
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "ETL RESULT"
    )

    print(
        "=" * 80
    )

    print(
        final_message.content
    )


def run_analytics():
    question = """
Tell me which books in the Gold books_phase2i_modern dataset
have the highest edition counts?

Return the title, first publication year, and edition count,
ordered from highest edition count to lowest. 
"""

    response = (
        data_engineer.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=question
                    )
                ]
            }
        )
    )

    final_message = (
        response["messages"][-1]
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "ANALYTICS RESULT"
    )

    print(
        "=" * 80
    )

    print(
        final_message.content
    )


if __name__ == "__main__":
    run_etl()
    run_analytics()