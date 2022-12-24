irc xdcc serve bot

commands:

    \list
    \regex
    \get
    \help

requirements:

    pip install --user irc

usage:

    python bot.py --server irc.server.tld --chan '#channel' --root /path/to/files/ --port 3000 --addr 178.23.78.23

or

    python bot.py --server irc.server.tld:6666 --chan '#channel' --root /path/to/files --port 3000 --addr 178.23.78.23
