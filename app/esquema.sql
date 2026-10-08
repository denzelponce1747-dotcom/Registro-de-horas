-- Esquema del Sistema de Registro de Horas de MAJERIE S.R.L
--
-- Es el mismo esquema que la versión desplegada en Vercel, adaptado a SQLite:
-- TIMESTAMPTZ pasa a TEXT con la fecha en ISO, BOOLEAN a INTEGER (0/1) y
-- NUMERIC a REAL. Las restricciones CHECK y las claves foráneas se conservan
-- tal cual. Todas las sentencias son idempotentes.
--
-- Es el esquema de una base NUEVA. Los cambios posteriores a una base que ya
-- existe los hace `app/migraciones.py`, que además fija `PRAGMA user_version`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL DEFAULT '',
  role          TEXT NOT NULL CHECK (role IN ('colaborador', 'administrador')),
  password_hash TEXT NOT NULL,
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Parámetros de jornada, vacaciones, tarifa y periodo de cada colaborador.
CREATE TABLE IF NOT EXISTS collaborator_settings (
  user_id               TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  daily_target_hours    REAL NOT NULL DEFAULT 8.5,
  carried_balance_hours REAL NOT NULL DEFAULT 0,
  carried_vacation_days REAL NOT NULL DEFAULT 0,
  annual_vacation_days  REAL NOT NULL DEFAULT 20,
  -- 'heredada' usa la tarifa del proyecto; 'sin-tarifa' no genera monto.
  rate_mode             TEXT NOT NULL DEFAULT 'heredada'
                        CHECK (rate_mode IN ('heredada', 'sin-tarifa', 'propia')),
  rate_amount           REAL,
  rate_currency         TEXT CHECK (rate_currency IN ('CRC', 'USD', 'EUR', 'CHF')),
  period_from           TEXT NOT NULL,
  period_to             TEXT NOT NULL,
  -- Desde cuándo cuentan sus vacaciones. NULL = desde siempre. Lo mueve
  -- «Trasladar el saldo al año siguiente».
  vacation_since        TEXT
);

CREATE TABLE IF NOT EXISTS projects (
  id            TEXT PRIMARY KEY,
  code          TEXT NOT NULL,
  name          TEXT NOT NULL,
  leader        TEXT NOT NULL DEFAULT '',
  -- NULL = proyecto de la empresa, visible para todo el equipo.
  owner_id      TEXT REFERENCES users(id) ON DELETE CASCADE,
  -- NULL = sin tarifa asignada.
  rate_amount   REAL,
  rate_currency TEXT CHECK (rate_currency IN ('CRC', 'USD', 'EUR', 'CHF')),
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tarifa de una persona en un proyecto concreto. Es el nivel más
-- específico del tarifario después del propio registro: permite que dos
-- colaboradores cobren distinto en el mismo proyecto.
CREATE TABLE IF NOT EXISTS collaborator_project_rates (
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  rate_mode     TEXT NOT NULL DEFAULT 'heredada'
                CHECK (rate_mode IN ('heredada', 'sin-tarifa', 'propia')),
  rate_amount   REAL,
  rate_currency TEXT CHECK (rate_currency IN ('CRC', 'USD', 'EUR', 'CHF')),
  PRIMARY KEY (user_id, project_id)
);

CREATE TABLE IF NOT EXISTS time_entries (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entry_date     TEXT NOT NULL,
  start_time     TEXT NOT NULL,
  end_time       TEXT NOT NULL,
  project_id     TEXT NOT NULL,
  project_name   TEXT NOT NULL,
  notes          TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'aprobado'
                 CHECK (status IN ('aprobado', 'pendiente')),
  pending_action TEXT NOT NULL DEFAULT ''
                 CHECK (pending_action IN ('', 'creacion', 'edicion', 'eliminacion')),
  pending_reason TEXT NOT NULL DEFAULT '',
  rate_mode      TEXT NOT NULL DEFAULT 'heredada'
                 CHECK (rate_mode IN ('heredada', 'sin-tarifa', 'propia')),
  rate_amount    REAL,
  rate_currency  TEXT CHECK (rate_currency IN ('CRC', 'USD', 'EUR', 'CHF')),
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS time_entries_user_date_idx ON time_entries (user_id, entry_date);
CREATE INDEX IF NOT EXISTS time_entries_status_idx ON time_entries (status);

-- El almuerzo se registra una sola vez por jornada.
CREATE TABLE IF NOT EXISTS lunches (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lunch_date TEXT NOT NULL,
  minutes    INTEGER NOT NULL DEFAULT 0 CHECK (minutes >= 0 AND minutes <= 240),
  PRIMARY KEY (user_id, lunch_date)
);

CREATE TABLE IF NOT EXISTS absences (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind              TEXT NOT NULL
                    CHECK (kind IN ('vacaciones', 'permiso-personal', 'cita-medica', 'incapacidad', 'otra')),
  from_date         TEXT NOT NULL,
  to_date           TEXT NOT NULL,
  days              REAL NOT NULL,
  accumulated_hours REAL NOT NULL DEFAULT 0,
  notes             TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (status IN ('pendiente', 'aprobada', 'rechazada')),
  -- Nombre de la persona administradora que resolvió, no un identificador.
  decided_by        TEXT NOT NULL DEFAULT '',
  decided_at        TEXT,
  decision_note     TEXT NOT NULL DEFAULT '',
  created_at        TEXT NOT NULL DEFAULT (date('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS absences_user_idx ON absences (user_id);
CREATE INDEX IF NOT EXISTS absences_status_idx ON absences (status);

CREATE INDEX IF NOT EXISTS absences_user_from_idx ON absences (user_id, from_date);

-- Periodo por omisión que hereda un colaborador nuevo. Una sola fila.
CREATE TABLE IF NOT EXISTS app_settings (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  period_from TEXT NOT NULL,
  period_to   TEXT NOT NULL
);

-- Datos sueltos del sistema: cuándo se creó, qué cuentas de Microsoft
-- pueden recuperar el acceso de administración…
CREATE TABLE IF NOT EXISTS meta (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);

-- Quién cambió qué, cuándo y desde qué computadora. Se conservan los
-- últimos cambios (ver `app/historial.py`).
CREATE TABLE IF NOT EXISTS historial (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  momento TEXT NOT NULL,
  usuario TEXT NOT NULL DEFAULT '',
  cuenta  TEXT NOT NULL DEFAULT '',
  equipo  TEXT NOT NULL DEFAULT '',
  accion  TEXT NOT NULL
);
