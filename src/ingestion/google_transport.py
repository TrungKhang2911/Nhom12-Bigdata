"""Bound Google scraper calls, including parsing, using an isolated process."""
import multiprocessing


def _worker(connection, operation, app_id, kwargs):
    try:
        from google_play_scraper import app, reviews
        result = {'app': app, 'reviews': reviews}[operation](app_id, **kwargs)
        connection.send((True, result))
    except Exception as exc:
        connection.send((False, exc))
    finally:
        connection.close()


def call(operation, app_id, kwargs, timeout=45.0):
    """No global socket settings or monkeypatching of library HTTP internals."""
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, operation, app_id, kwargs), daemon=True)
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            raise TimeoutError(f'Google {operation} exceeded {timeout}s for {app_id}')
        try:
            success, payload = parent.recv()
        except EOFError as exc:
            raise RuntimeError('Google worker exited without a result') from exc
        if not success:
            raise payload
        return payload
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            process.close()
