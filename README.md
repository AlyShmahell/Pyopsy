# Pyopsy

The definitive concise python profiler, with minimal dependency and a small footprint, it is feature-complete with a cli, a web UI and dedicated file-logging.


## Install

- requires Python 3.12 or later.
- Install the package with pip:
    ```sh
    pip install pyopsy
    ```

## Usage

- Import `profiler` and `session` from `pyopsy`.
- Put `@pyopsy.profiler` on a function.
- The decorator supports a function, a generator, an async function, and an async generator.
- `str()` on a marked function returns wall time and memory as JSON.
- Open one session with `pyopsy.session()`.
- The session opens a web page on `127.0.0.1`.
- Set `cli=True` to draw a terminal screen.
- Set `log` to a file path to append JSONL snapshots.

## Tutorial
check [example.py](https://github.com/AlyShmahell/Pyopsy/blob/main/example.py) for a more complete and hands-on tutorial, it is setup to give a sample use-case for 4 different types of functions:
- normal function
- normal generator
- async function
- async generator

It also has a usecase for line recording.

The following is a sample run:
![](docs/1.%20summary+marked.png)
![](docs/2.%20calls+functions.png)
![](docs/3.%20lines.png)