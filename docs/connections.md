# Connections

How a source's connection is written, encrypted, stored and used, how to require TLS, where the keys live, and what this protects against.

A connection is everything a connector needs to reach its source: address, user, password or token. It is written as a block in the definition. Secrets appear in it only as placeholders.

```toml
[erp.connection]
string = "Driver={ODBC Driver 18 for SQL Server};Server=sqlsrv01;Database=erp;UID=reader;PWD=$ERP_PASSWORD"

[weather.connection]
url   = "https://api.example.org"
token = "$WEATHER_TOKEN"
```

```mermaid
flowchart LR
    D["definition<br/>connection block with placeholders"] --> A[rowvioli apply]
    E["environment at deploy time<br/>ERP_PASSWORD=…"] --> A
    P["worker.pub<br/>next to the definition"] -.-> A
    A -->|"one ciphertext per source"| S[("_rowvioli.sources")]
    S -->|"read at the start of a run"| W[Worker]
    K["worker.key<br/>file on the worker"] -.->|"decrypts in memory"| W
    W -->|"hands the block to the connector"| Q[(Source)]
```

- **A person** writes the block and makes sure the variables are set when `apply` runs. A secret manager holds plain values such as a token or a password. Nobody builds a connection string by hand in a variable, and nobody percent-encodes a value by hand.
- **`apply`** fills in the placeholders, encrypts the block as a whole with the public key and stores one ciphertext per source. It aborts if a variable is missing.
- **The connector** receives the decrypted block as a dict. Which fields it expects is part of its documentation: `url` for `postgres`, `string` for `odbc`, `url` and `token` for `rest`, `path` for `file`.

The address of a source is visible in the definition and in its review, and still encrypted in the target. Someone who can only write to the target cannot point a password at another server. If the source is a cluster, that is part of the connection string and nothing rowvioli has to know.

For test and production with different addresses, the address becomes a placeholder too, for example `url = "$WEATHER_URL"`.

## TLS

rowvioli sets no TLS option of its own. The URL decides, and without a setting libpq tries TLS and falls back to plain text unnoticed. To require it, and to check the server's certificate and name, add `sslmode=verify-full` (and `sslrootcert=<file>` if the certificate authority is not in the system's store) to the target's address and to the `url` of every `postgres` source:

```sh
export ROWVIOLI_TARGET_URL='postgresql://etl@pg01/dwh?sslmode=verify-full'
```

```toml
[erp.connection]
url = "postgresql://reader:$ERP_PASSWORD@erp-db01/erp?sslmode=verify-full"
```

A server without TLS then fails the command with `server does not support SSL, but SSL was required`. A `rest` source is encrypted when its `url` starts with `https`; with `http` the token travels in clear text. For `odbc` the driver's own settings decide.

## How it is encrypted

- **A standard construction, not a home-made one.** Connections are encrypted as libsodium sealed boxes through PyNaCl: an X25519 key exchange with a one-time key, then authenticated encryption with XSalsa20-Poly1305. GitHub uses the same construction for repository secrets set through its API.
- **Tampering is detected.** A single flipped bit makes decryption fail.
- **Swapping is detected.** The name of the source is encrypted together with its connection. A ciphertext copied to another source is rejected.
- **Equal values look different.** Encrypting the same connection twice gives two different ciphertexts. `apply` therefore writes a new ciphertext every time, with the same content.

All four were tried out in [experiments/07_secrets.py](../experiments/07_secrets.py), with a single value in place of a block.

## Where the keys live

There is one key pair for all workers of a target.

| Key | Where | Who may see it |
|---|---|---|
| Public key | `worker.pub`, a file next to the definition | everybody. It changes only through a merge request. |
| Private key | a file on each worker, `worker.key` in its working directory or the one `ROWVIOLI_KEY_FILE` names, mode 600 | the service user of the worker |

- The private key is never in the database, never in Git, and never passed as the value of an environment variable.
- The public key is taken from the file next to the definition (`worker.pub` in the parent of the directory `apply` gets), not from the database. Someone with write access to the database therefore cannot slip in a key of their own.
- A worker can hold several private keys, which is what makes rotation possible.
- A second machine gets a copy of `worker.key`, made where `rowvioli key new` was run. `key new` there would create a different pair, which belongs to no `worker.pub` that was applied: every table then fails with `holds no private key <id>`, and the reason names both ways out, the right `worker.key` or `apply` again with the new `worker.pub`. `key new` is for a new target.

## What happens to the decrypted connection

- It exists only in the memory of the run's process and of the connector.
- It is never written to `_rowvioli.runs`, to the answer on stdout or to a log.
- Database drivers like to quote the connection string in error messages, and parts of a value they cannot parse. The program removes the values of the connection from every error text before it stores or prints it: each value as written, stripped of surrounding whitespace (a token read from a file ends in a newline) and as a driver quotes it inside quotes, and the password inside a URL or an ODBC string as written and decoded. For the target it removes the password of `ROWVIOLI_TARGET_URL` only, so user and host stay readable in its errors. This is best effort ([open points](open-points.md)). A password in a URL is the case where a driver quotes a part: `apply` percent-encodes a value that lands in the user info (`scheme://user:$PASSWORD@host`), so the driver never misparses it.

## Rotation and loss

A new password: change the variable and run `apply` again.

A new key pair:

1. `rowvioli key new` creates a new pair.
2. The new private key is added to every worker, next to the old one.
3. The new public key replaces `worker.pub`. `apply` encrypts every connection anew.
4. The old private key is removed.

If the private key is lost, a new pair and one `apply` restore everything, because the definition and the environment still hold all values.

## What this protects against, and what not

| Situation | Protected |
|---|---|
| Someone reads the database, a backup or a replica | yes, they see ciphertext only |
| Someone with write access changes or swaps a ciphertext | yes, decryption fails |
| Someone with write access changes a definition to redirect a connection | yes for the shipped connectors, the address is inside the ciphertext. A REST `path` that would leave the connection's host fails the run, and so does a `file` table outside the connection's `path`. |
| A worker is compromised | **no**. It holds the private key and a database connection and can read every connection. |
| The place where `apply` runs is compromised | **no**. It holds every secret in its environment. |
| Someone with write access puts back an older ciphertext of the same source | **no** |

The encryption will not be the weak point. The private key file and the deployment environment are. Two measures limit the damage: accounts in the source systems that may only read, and as few people as possible who can log in to a worker or change the deployment.

A connector is code the operator trusts. It receives the decrypted connection and can do with it what it wants. The promise above holds for the shipped connectors.
