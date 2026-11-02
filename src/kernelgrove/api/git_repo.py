"""Control de versiones sobre `git`, reducido a lo que ve el usuario.

El modelo es el de git y se maneja como en VS Code: **área de preparación**
(qué ficheros entran en la próxima versión y cuáles no), descartar cambios
fichero a fichero, y el historial de commits — con su mensaje y su sha
corto, sin numerarlos. Los números «v1, v2…» que hubo aquí eran una
invención de esta interfaz: no existen en el repositorio, no coinciden con
lo que dice `git log` ni con lo que ve nadie más que abra el proyecto, y en
cuanto se puede volver a un commit concreto lo que hace falta es poder
nombrarlo como lo nombra git.

Lo que sigue fuera es lo que necesita configuración aparte: ramas, remotos
(push/pull), stash y resolución de conflictos. Un fichero en conflicto se
enseña con su letra (`U`) y se puede preparar como cualquier otro, pero no
hay herramienta de fusión aquí.

Se versiona el **proyecto**, no cada fichero por su cuenta: un device tree es
un `.dts` más los `.dtsi` que incluye, y numerar cada fichero aparte deja sin
respuesta la única pregunta que importa ("¿qué combinación funcionaba?"). La
lectura por fichero existe igual, pero como *filtro* del mismo historial
(`path=` en `versions`).

Se habla con el `git` del sistema por `subprocess`: no añade ninguna
dependencia y son seis comandos. Si no hay `git` en el PATH nada de esto
revienta — `git_available()` lo dice y `find_repo` devuelve `None`, con lo
que la capa de interfaz se apaga sola.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
from operator import attrgetter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple, Union

# Separador de campos dentro de una línea de `git log`: un carácter de
# control que no puede aparecer en el asunto de un commit ni en un nombre.
_FIELD_SEP = "\x1f"

# Tope para cualquier comando. Son todos operaciones locales de milisegundos,
# pero se llaman desde el hilo de la interfaz: si uno se queda colgado
# (un repositorio enorme, un disco de red), es preferible un error a una
# ventana congelada para siempre.
_TIMEOUT_SECONDS = 20

# En Windows cada `subprocess` abre una consola que parpadea sobre la
# ventana. Esta bandera lo evita y en el resto de sistemas no existe (0).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitError(RuntimeError):
    """Un comando de git ha fallado; el mensaje es el que dio git."""


class GitMissingError(GitError):
    """No hay `git` instalado, o no está en el PATH."""


@dataclass(frozen=True)
class FileChange:
    """Un fichero tocado, en uno de los dos grupos del panel."""

    path: str
    # M modificado, A añadido, D borrado, R renombrado, ? sin seguimiento,
    # U en conflicto.
    status: str
    # En qué lado está: preparado para la próxima versión, o solo cambiado.
    staged: bool = False
    untracked: bool = False


@dataclass(frozen=True)
class RepoStatus:
    """Los dos grupos de cambios, tal como se enseñan.

    Un mismo fichero puede salir en los dos a la vez (código `MM`: una
    modificación ya preparada y otra posterior que no lo está), y eso es
    exactamente lo que hay que enseñar — cada mitad se prepara, se descarta
    y se compara por su cuenta.
    """

    staged: List[FileChange]
    unstaged: List[FileChange]

    def is_empty(self) -> bool:
        """Si no hay absolutamente nada que guardar."""
        return not self.staged and not self.unstaged


@dataclass
class LineChanges:
    """Líneas del texto actual que difieren de la última versión guardada."""

    added: Set[int] = field(default_factory=set)
    modified: Set[int] = field(default_factory=set)
    deleted: Set[int] = field(default_factory=set)

    def is_empty(self) -> bool:
        """Si no hay nada que marcar."""
        return not (self.added or self.modified or self.deleted)


@dataclass(frozen=True)
class HeadState:
    """Dónde está HEAD ahora mismo: en qué rama, o en qué commit suelto.

    Va junto y no en tres llamadas sueltas porque el panel lo compara entero
    para decidir si tiene que repintarse (ver `GitPanel.refresh`), y porque
    las tres preguntas son la misma: «¿dónde estoy?».
    """

    branch: str = ""
    sha: str = ""
    short: str = ""

    @property
    def detached(self) -> bool:
        """Si se está sobre un commit suelto y no sobre la punta de una rama.

        Es el estado en el que se acaba tras un `checkout` de una versión
        anterior, y el que hay que **ver**: guardar aquí no mueve ninguna
        rama, y la versión nueva se pierde en cuanto se vuelva a otra.
        """
        return bool(self.sha) and not self.branch


@dataclass(frozen=True)
class Version:
    """Una versión guardada: un commit, con lo que hace falta para enseñarlo."""

    sha: str
    short: str
    author: str
    date: str
    message: str
    # Ramas locales que apuntan a este commit, la actual la primera. Es lo
    # que el panel dibuja como etiqueta sobre el grafo, igual que Git Graph
    # y que la vista de VS Code: en un historial, «dónde está `main`» se lee
    # sobre la línea, no en un desplegable aparte.
    branches: Tuple[str, ...] = ()


def _local_branches(refs: str) -> Tuple[str, ...]:
    """Ramas locales de un `%D`, con la actual la primera.

    `%D` trae de todo —`HEAD -> main, experimento, tag: v1,
    origin/main`— y aquí solo interesan las ramas de este repositorio: a
    una etiqueta remota no se le puede hacer `checkout` sin más, y una
    etiqueta de versión no es un sitio al que volver. `HEAD -> x` marca la
    rama en la que se está, y se queda delante para que se dibuje primero.
    """
    actual = ""
    otras: List[str] = []
    for parte in refs.split(","):
        nombre = parte.strip()
        if not nombre or nombre.startswith("tag: ") or "/" in nombre:
            continue
        if nombre.startswith("HEAD -> "):
            actual = nombre[len("HEAD -> "):].strip()
        elif nombre != "HEAD":
            otras.append(nombre)
    return tuple(([actual] if actual else []) + otras)


def git_available() -> bool:
    """Si hay un `git` ejecutable en el PATH."""
    return shutil.which("git") is not None


def find_repo(path: Union[str, Path]) -> Optional["GitRepo"]:
    """Repositorio que contiene `path`, o `None` si no hay (o no hay git).

    Devolver `None` en vez de lanzar es deliberado: "esta carpeta no está
    versionada" y "este ordenador no tiene git" son estados normales de la
    aplicación, no errores que haya que capturar en cada llamada.
    """
    folder = Path(path)
    if not git_available() or not folder.is_dir():
        return None
    try:
        top_level = _run(["rev-parse", "--show-toplevel"], folder).strip()
    except GitError:
        return None
    return GitRepo(Path(top_level)) if top_level else None


def init_repo(path: Union[str, Path]) -> "GitRepo":
    """Empieza a versionar `path` (`git init`) y devuelve el repositorio."""
    folder = Path(path)
    _run(["init"], folder)
    return GitRepo(folder)


def _run(args: Sequence[str], cwd: Path, check: bool = True) -> str:
    """Ejecuta un comando de git en `cwd` y devuelve su salida estándar.

    Con `check=False` no se mira el código de salida: hay comandos que lo
    usan como respuesta y no como fallo (`diff --no-index` devuelve 1 cuando
    hay diferencias, que es precisamente el caso interesante).
    """
    if not git_available():
        raise GitMissingError("git is not installed or not on PATH")
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            # Un `.dts` puede traer cualquier codificación en un comentario;
            # un carácter suelto ilegible no puede tumbar el panel entero.
            errors="replace",
            timeout=_TIMEOUT_SECONDS,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        # git ha desaparecido entre la comprobación y la llamada.
        raise GitMissingError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out") from exc
    if check and completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise GitError(message or f"git {args[0]} failed")
    return completed.stdout


class GitRepo:
    """Un repositorio ya localizado, con las operaciones del panel."""

    def __init__(self, root: Path):
        """Guarda la raíz del repositorio (la que dio `rev-parse`)."""
        self.root = Path(root)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    def branch(self) -> str:
        """Rama actual, o cadena vacía si aún no se puede saber.

        Se muestra aunque el modelo del panel no hable de ramas: quien sí
        sabe git necesita ver dónde está antes de guardar nada, sobre todo
        si abrió una carpeta que ya era un repositorio suyo.
        """
        return _run(["symbolic-ref", "--short", "HEAD"], self.root, check=False).strip()

    def head(self) -> HeadState:
        """Rama y commit en los que se está. Todo con `check=False`.

        Un repositorio recién creado no tiene HEAD y eso no es un error:
        devuelve un estado vacío, que es lo que el panel sabe pintar.
        """
        sha = _run(
            ["rev-parse", "--verify", "--quiet", "HEAD"], self.root, check=False
        ).strip()
        if not sha:
            return HeadState()
        return HeadState(branch=self.branch(), sha=sha, short=sha[:7])

    def create_branch(self, name: str, ref: str = "HEAD") -> None:
        """Abre una rama en `ref` y se sitúa en ella.

        Es lo que le falta a un `checkout` de una versión antigua para
        servir de algo más que mirar: ahí no se está en ninguna rama, y lo
        que se guarde se pierde al volver. Con una rama abierta en ese
        punto, se guarda como en cualquier otra.

        No comprueba si el nombre ya existe: `git` se niega solo y dice por
        qué, que es mejor mensaje que uno nuestro.
        """
        _run(["checkout", "-b", name, ref], self.root)


    def has_commits(self) -> bool:
        """Si hay al menos una versión guardada (un repo recién creado no)."""
        return bool(
            _run(
                ["rev-parse", "--verify", "--quiet", "HEAD"], self.root, check=False
            ).strip()
        )

    def status(self) -> RepoStatus:
        """Cambios preparados y sin preparar, cada grupo ordenado por ruta.

        Las dos columnas de `git status --porcelain` son justo esa
        separación: la primera dice qué le pasa al fichero en el índice (lo
        preparado) y la segunda qué le pasa en el disco. Un fichero con las
        dos ocupadas aparece en los dos grupos.
        """
        # `-z` en vez de la salida normal: separa registros con NUL, así que
        # no hay que adivinar nada con nombres que llevan espacios o comillas.
        # `-uall` lista los ficheros nuevos uno a uno en lugar de colapsarlos
        # en su carpeta, que es lo que hace falta para poder pinchar cada uno.
        raw = _run(["status", "--porcelain=v1", "-z", "-uall"], self.root)
        entries = raw.split("\0")
        staged: List[FileChange] = []
        unstaged: List[FileChange] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            if "R" in code or "C" in code:
                # Un renombrado ocupa DOS registros: el nuevo nombre y, en el
                # siguiente, el viejo. Ese segundo hay que saltárselo.
                index += 1
            if code == "??":
                unstaged.append(
                    FileChange(path=path, status="?", staged=False, untracked=True)
                )
                continue
            in_index, in_worktree = code[0], code[1]
            if in_index not in " ?":
                staged.append(FileChange(path=path, status=in_index, staged=True))
            if in_worktree not in " ?":
                unstaged.append(FileChange(path=path, status=in_worktree))
        by_path = attrgetter("path")
        return RepoStatus(
            staged=sorted(staged, key=by_path), unstaged=sorted(unstaged, key=by_path)
        )

    def is_tracked(self, path: str) -> bool:
        """Si git ya conoce ese fichero (no es uno nuevo sin añadir)."""
        return (
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", path],
                cwd=str(self.root),
                capture_output=True,
                creationflags=_NO_WINDOW,
            ).returncode
            == 0
        )

    # ------------------------------------------------------------------
    # Historial
    # ------------------------------------------------------------------
    def versions(self, limit: int = 200, path: Optional[str] = None) -> List[Version]:
        """Versiones guardadas, de la más reciente a la más antigua.

        Con `path` se filtra por un fichero, sin dejar de ser el mismo
        historial del proyecto.
        """
        if not self.has_commits():
            return []
        # `%D` trae los refs que apuntan a cada commit en la misma pasada:
        # una etiqueta de rama sobre el grafo no vale una segunda llamada a
        # git, y menos una por commit.
        fields = _FIELD_SEP.join(["%H", "%h", "%an", "%ad", "%s", "%D"])
        args = ["log", f"--max-count={limit}", f"--format={fields}", "--date=short"]
        # **Fuera de una rama se listan también las ramas.** `git log` cuenta
        # desde HEAD, así que tras un `checkout` de una versión antigua la
        # lista se quedaba con esa y sus antepasadas: justo el momento en que
        # hace falta ver las de después para poder volver a una. Con rama
        # puesta no se añade nada y la lista es la de siempre, la de esa
        # rama y no la de todas.
        if not self.branch():
            args.append("--branches")
        if path:
            args += ["--", path]
        versions: List[Version] = []
        for line in _run(args, self.root).splitlines():
            parts = line.split(_FIELD_SEP)
            if len(parts) != 6:
                continue
            sha, short, author, date, message, refs = parts
            versions.append(
                Version(
                    branches=_local_branches(refs),
                    sha=sha,
                    short=short,
                    author=author,
                    date=date,
                    message=message,
                )
            )
        return versions

    # ------------------------------------------------------------------
    # Diferencias
    # ------------------------------------------------------------------
    def working_diff(self, path: str, staged: bool = False) -> str:
        """Qué ha cambiado en `path`, en el lado que se pida.

        Los dos lados se comparan contra cosas distintas y por eso hay dos
        diffs: lo preparado es índice contra la última versión (`--cached`),
        y lo no preparado es disco contra el índice. Un fichero con cambios
        en los dos sitios enseña una mitad en cada grupo, igual que en VS
        Code.
        """
        if path.endswith("/"):
            # Una carpeta entera sin seguimiento: no hay diff que enseñar.
            return ""
        if staged:
            return _run(["diff", "--cached", "--", path], self.root)
        if self.is_tracked(path):
            return _run(["diff", "--", path], self.root)
        # Fichero nuevo: se enseña entero como añadido. `--no-index` devuelve
        # 1 justamente cuando hay diferencias, de ahí el `check=False`.
        return _run(
            ["diff", "--no-index", "--", "/dev/null", path], self.root, check=False
        )

    def version_diff(self, sha: str) -> str:
        """Todo lo que cambió en una versión respecto de la anterior."""
        return _run(["show", sha], self.root)

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    def stage(self, paths: Sequence[str]) -> None:
        """Mete esos ficheros en la próxima versión.

        `add` vale igual para uno nuevo, uno modificado y uno borrado: lo
        que registra es el estado actual del fichero, no una operación.
        """
        if paths:
            _run(["add", "--", *paths], self.root)

    def stage_all(self) -> None:
        """Prepara todo lo que haya cambiado."""
        _run(["add", "-A"], self.root)

    def unstage(self, paths: Sequence[str]) -> None:
        """Saca esos ficheros de la próxima versión, sin tocar el disco."""
        if not paths:
            return
        if self.has_commits():
            _run(["reset", "--quiet", "HEAD", "--", *paths], self.root)
        else:
            # Sin ninguna versión todavía no hay HEAD contra el que resetear;
            # sacar del índice un fichero nuevo es quitarlo de ahí y ya.
            _run(["rm", "--cached", "--quiet", "-r", "--", *paths], self.root)

    def discard(self, changes: Sequence[FileChange]) -> None:
        """Deshace cambios del disco. **Irreversible**: no hay dónde buscarlos.

        Un fichero con seguimiento vuelve a lo que dice el índice
        (`checkout --`), que es lo que hace "Discard Changes" en VS Code.
        Uno sin seguimiento no tiene estado anterior al que volver, así que
        se borra (`clean -fd`, que se ocupa también de una carpeta entera).
        """
        tracked = [change.path for change in changes if not change.untracked]
        untracked = [change.path for change in changes if change.untracked]
        if tracked:
            _run(["checkout", "--", *tracked], self.root)
        if untracked:
            _run(["clean", "-fdq", "--", *untracked], self.root)

    def save_version(self, message: str) -> None:
        """Guarda una versión con lo que esté preparado, y solo con eso."""
        _run(["commit", "-m", message], self.root)

    def checkout(self, ref: str) -> None:
        """Se sitúa en `ref`: un commit (HEAD desprendido) o una rama.

        Es el `checkout` de git, sin adornos, y por eso vale para las dos
        direcciones: ir a una versión anterior a mirarla, y volver a la rama
        de la que se salió.

        Antes esto era un `checkout <sha> -- .` que solo devolvía el
        contenido, para no dejar a nadie en un HEAD desprendido «del que no
        sabría salir». La objeción era buena y la respuesta no: lo que hacía
        falta no era esconder la operación sino **enseñar dónde se está** y
        por dónde se sale (ver `HeadState.detached` y el panel). Git se
        niega solo si hay cambios sin guardar que se perderían, y su
        mensaje es el que se enseña.
        """
        _run(["checkout", ref], self.root)

    def reset(self, sha: str, hard: bool = False) -> None:
        """Mueve la rama a `sha`, tirando las versiones posteriores.

        `--mixed` por defecto: la historia se corta ahí pero los ficheros se
        quedan como están, ahora como cambios sin guardar — se puede
        rehacer la versión sin perder una línea. Con `hard` se van también
        los ficheros, y eso no lo recupera nada desde aquí, así que quien
        llama tiene que preguntar antes.

        Es distinto de `restore`: aquel deja la historia intacta y solo
        devuelve el contenido; este reescribe dónde está la rama.
        """
        _run(["reset", "--hard" if hard else "--mixed", sha], self.root)

    def file_in_index(self, path: str) -> Optional[str]:
        """Contenido preparado de `path` (`git show :fichero`), o `None`.

        Es la referencia contra la que el editor marca los cambios del
        margen, y es **el índice y no HEAD** porque es el criterio de VS
        Code: preparar un cambio lo saca del margen, igual que allí. Tiene
        sentido con el resto del panel — lo preparado ya está descrito como
        «lo que va en la próxima versión», y seguir marcándolo repetiría en
        el editor lo que la lista de cambios ya dice.

        `None` significa «no hay con qué comparar»: el fichero no está en el
        índice (es nuevo y sin preparar) o el repositorio está recién hecho.
        """
        result = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout


def changed_lines(before: Optional[str], after: str) -> "LineChanges":
    """Qué líneas de `after` no estaban -o no estaban así- en `before`.

    Se compara texto contra texto y no se llama a `git diff` porque lo que
    se marca en el editor es **lo que hay escrito ahora**, que puede no
    estar aún en el disco: diffear el fichero guardado dejaría el resaltado
    una versión por detrás de lo que se está viendo. `before` a `None` (un
    fichero nuevo, o un repositorio sin ninguna versión) significa que todo
    es nuevo.

    Las líneas van 1-based, como las del editor. `deleted` no son líneas de
    `after` sino los sitios donde algo desapareció: se marca la línea
    anterior al hueco, que es donde se puede pintar algo.
    """
    lines = after.splitlines()
    if before is None:
        return LineChanges(added=set(range(1, len(lines) + 1)))

    changes = LineChanges()
    matcher = difflib.SequenceMatcher(None, before.splitlines(), lines, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            changes.added.update(range(j1 + 1, j2 + 1))
        elif tag == "replace":
            changes.modified.update(range(j1 + 1, j2 + 1))
        elif tag == "delete":
            # El hueco no ocupa ninguna línea de `after`: se marca la de
            # justo antes, y la primera si lo borrado estaba al principio.
            changes.deleted.add(max(1, j1))
    return changes
