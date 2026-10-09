# Pyopsy

The definitive concise python profiler, with minimal dependency and a small footprint, it is feature-complete with a cli, a web UI and dedicated file-logging.


## Install

- requires Python 3.12 or later.
- Install the package with pip:
    ```sh
    pip install pyopsy
    ```

## Usage
check [example.py](/example.py) for a tutorial, it is setup to give a sample usecase for 4 different types of functions:
- normal function
- normal generator
- async function
- async generator

It also has a usecase for line recording.

The session at the end logs to the cli, to the live web ui page, and to a file; as a general showcase of capability, and the following is a sample run:
![](docs/1.%20summary+marked.png)
![](docs/2.%20calls+functions.png)
![](docs/3.%20lines.png)