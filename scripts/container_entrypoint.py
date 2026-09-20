import os
import sys

from pathlib import Path


APP_UID = 10001
APP_GID = 10001

PERSIST_ROOT = Path(
    os.environ.get(
        "PERSIST_ROOT",
        "/app/runtime",
    )
)


RUNTIME_DIRECTORIES = (
    PERSIST_ROOT / "data",
    (
        PERSIST_ROOT
        / "dbt"
        / "generated_metadata"
    ),
    (
        PERSIST_ROOT
        / "dbt"
        / "models"
        / "sources"
    ),
    (
        PERSIST_ROOT
        / "dbt"
        / "models"
        / "staging"
        / "generated"
    ),
    (
        PERSIST_ROOT
        / "dbt"
        / "models"
        / "marts"
        / "generated"
    ),
)


def _prepare_runtime_storage() -> None:
    """
    Ensure persistent runtime directories exist.

    Cloud platforms may mount persistent storage as
    root even when the image normally runs as a
    non-root user.

    If started as root, prepare the volume and then
    drop privileges before starting the application.
    """

    for directory in RUNTIME_DIRECTORIES:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    if os.geteuid() != 0:
        return

    for root, directories, files in os.walk(
        PERSIST_ROOT
    ):
        os.chown(
            root,
            APP_UID,
            APP_GID,
            follow_symlinks=False,
        )

        for directory in directories:
            os.chown(
                os.path.join(
                    root,
                    directory,
                ),
                APP_UID,
                APP_GID,
                follow_symlinks=False,
            )

        for file_name in files:
            os.chown(
                os.path.join(
                    root,
                    file_name,
                ),
                APP_UID,
                APP_GID,
                follow_symlinks=False,
            )

    os.setgroups(
        []
    )

    os.setgid(
        APP_GID
    )

    os.setuid(
        APP_UID
    )


def main() -> None:
    _prepare_runtime_storage()

    if len(sys.argv) < 2:
        raise RuntimeError(
            "Container entrypoint received "
            "no command."
        )

    os.execvp(
        sys.argv[1],
        sys.argv[1:],
    )


if __name__ == "__main__":
    main()
