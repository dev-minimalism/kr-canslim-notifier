"""Database connection module with SSH tunnel support."""

import os
import socket
import threading
from contextlib import contextmanager
from typing import Optional, Generator

import paramiko
import psycopg2
from psycopg2.extras import RealDictCursor

from .settings import settings


class SSHTunnel:
    """SSH tunnel manager for database connection."""

    def __init__(self):
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.local_port: int = 0
        self._lock = threading.Lock()
        self._is_connected = False

    def _find_free_port(self) -> int:
        """Find a free local port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]

    def connect(self) -> int:
        """
        Establish SSH tunnel and return local port.

        Returns:
            Local port number for database connection.
        """
        with self._lock:
            if self._is_connected:
                return self.local_port

            try:
                # Expand SSH key path
                key_path = os.path.expanduser(settings.SSH_KEY_PATH)

                # Create SSH client
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Load private key
                private_key = paramiko.RSAKey.from_private_key_file(key_path)

                # Connect to SSH server
                self.ssh_client.connect(
                    hostname=settings.SSH_HOST,
                    port=settings.SSH_PORT,
                    username=settings.SSH_USER,
                    pkey=private_key,
                )

                # Find free local port
                self.local_port = self._find_free_port()

                # Create port forwarding
                transport = self.ssh_client.get_transport()
                transport.request_port_forward("localhost", self.local_port)

                # Start local forwarding thread
                self._start_forward_thread(transport)

                self._is_connected = True
                print(f"✅ SSH tunnel established (local port: {self.local_port})")
                return self.local_port

            except Exception as e:
                print(f"❌ SSH tunnel failed: {e}")
                self.close()
                raise

    def _start_forward_thread(self, transport: paramiko.Transport):
        """Start port forwarding in background thread."""

        def forward_handler():
            while self._is_connected:
                try:
                    channel = transport.accept(timeout=1)
                    if channel is None:
                        continue

                    # Connect to remote database
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.connect((settings.DB_HOST, settings.DB_PORT))

                    # Forward data between channel and socket
                    def forward(src, dst):
                        try:
                            while True:
                                data = src.recv(1024)
                                if not data:
                                    break
                                dst.sendall(data)
                        except:
                            pass
                        finally:
                            src.close()
                            dst.close()

                    threading.Thread(
                        target=forward, args=(channel, sock), daemon=True
                    ).start()
                    threading.Thread(
                        target=forward, args=(sock, channel), daemon=True
                    ).start()

                except Exception:
                    if not self._is_connected:
                        break

        threading.Thread(target=forward_handler, daemon=True).start()

    def close(self):
        """Close SSH tunnel."""
        with self._lock:
            self._is_connected = False
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
            print("🔒 SSH tunnel closed")


class DatabaseConnection:
    """PostgreSQL database connection manager with SSH tunnel."""

    def __init__(self):
        self.tunnel = SSHTunnel()
        self._connection: Optional[psycopg2.extensions.connection] = None

    def connect(self) -> psycopg2.extensions.connection:
        """
        Establish database connection through SSH tunnel.

        Returns:
            PostgreSQL connection object.
        """
        if self._connection and not self._connection.closed:
            return self._connection

        # Establish SSH tunnel
        local_port = self.tunnel.connect()

        # Connect to database through tunnel
        self._connection = psycopg2.connect(
            host="localhost",
            port=local_port,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
        )
        self._connection.autocommit = False
        print(f"✅ Database connected: {settings.DB_NAME}")
        return self._connection

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True) -> Generator:
        """
        Get database cursor as context manager.

        Args:
            dict_cursor: If True, return RealDictCursor for dict-like row access.

        Yields:
            Database cursor.
        """
        conn = self.connect()
        cursor_factory = RealDictCursor if dict_cursor else None
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def execute(self, query: str, params: tuple = None) -> list:
        """
        Execute query and return results.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            List of result rows as dictionaries.
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            if cursor.description:
                return cursor.fetchall()
            return []

    def execute_one(self, query: str, params: tuple = None) -> Optional[dict]:
        """
        Execute query and return single result.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            Single result row as dictionary or None.
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            if cursor.description:
                return cursor.fetchone()
            return None

    def close(self):
        """Close database and SSH tunnel connections."""
        if self._connection and not self._connection.closed:
            self._connection.close()
            print("🔒 Database connection closed")
        self.tunnel.close()

    def init_schema(self):
        """Initialize database schema."""
        schema_sql = """
        -- Positions table for paper trading
        CREATE TABLE IF NOT EXISTS positions (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            entry_price DECIMAL(15, 2) NOT NULL,
            entry_date TIMESTAMP NOT NULL DEFAULT NOW(),
            pattern VARCHAR(100),
            stop_loss DECIMAL(15, 2),
            take_profit DECIMAL(15, 2),
            signal_data JSONB,
            status VARCHAR(20) DEFAULT 'open',
            exit_price DECIMAL(15, 2),
            exit_date TIMESTAMP,
            exit_reason VARCHAR(100),
            profit_pct DECIMAL(10, 4),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        -- Index for faster lookups
        CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker);
        CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
        CREATE INDEX IF NOT EXISTS idx_positions_entry_date ON positions(entry_date);

        -- Trade history table for closed positions
        CREATE TABLE IF NOT EXISTS trade_history (
            id SERIAL PRIMARY KEY,
            position_id INTEGER REFERENCES positions(id),
            ticker VARCHAR(20) NOT NULL,
            entry_price DECIMAL(15, 2) NOT NULL,
            entry_date TIMESTAMP NOT NULL,
            exit_price DECIMAL(15, 2) NOT NULL,
            exit_date TIMESTAMP NOT NULL,
            exit_reason VARCHAR(100),
            profit_pct DECIMAL(10, 4),
            holding_days INTEGER,
            pattern VARCHAR(100),
            created_at TIMESTAMP DEFAULT NOW()
        );

        -- Watchlist table
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL UNIQUE,
            name VARCHAR(100),
            added_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker);
        """

        with self.get_cursor() as cursor:
            cursor.execute(schema_sql)
        print("✅ Database schema initialized")


# Singleton instance
_db_instance: Optional[DatabaseConnection] = None


def get_db() -> DatabaseConnection:
    """Get database connection singleton."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseConnection()
    return _db_instance
