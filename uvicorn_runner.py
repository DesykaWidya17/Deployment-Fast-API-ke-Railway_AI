import os
import sys

if __name__ == "__main__":
    port = str(os.environ.get("PORT", "8000")).strip() or "8000"
    clean_args = []
    for arg in sys.argv[1:]:
        if "${PORT" in arg:
            clean_args.append(port)
        else:
            clean_args.append(arg)

    sys.argv = [sys.argv[0]] + clean_args
    from uvicorn.main import main
    main()
