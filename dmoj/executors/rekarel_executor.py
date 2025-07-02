import errno
import glob
import os
import re
import subprocess
import sys
import traceback
from collections import deque
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from dmoj.cptbox import Debugger, TracedPopen
from dmoj.cptbox.filesystem_policies import (
    ExactDir,
    ExactFile,
    FilesystemAccessRule,
    RecursiveDir,
)
from dmoj.error import CompileError, InternalError
from dmoj.executors.base_executor import AutoConfigOutput, VersionFlags, print_ansi
from dmoj.executors.compiled_executor import CompiledExecutor
from dmoj.executors.mixins import SingleDigitVersionMixin
from dmoj.judgeenv import skip_self_test
from dmoj.result import Result
from dmoj.utils.error import print_protection_fault
from dmoj.utils.unicode import utf8bytes, utf8text

# recomment = re.compile(r'/\*.*?\*/', re.DOTALL | re.U)
# restring = re.compile(r''''(?:\\.|[^'\\])'|"(?:\\.|[^"\\])*"''', re.DOTALL | re.U)
# reinline_comment = re.compile(r'//.*?(?=[\r\n])', re.U)
# reclass = re.compile(
#     r'\bpublic\s+(?:strictfp\s+)?(?:(?:abstract|final)\s+)?(?:strictfp\s+)?class\s+([\w$][\w$]*?)\b', re.U
# )
# repackage = re.compile(r'\bpackage\s+([^.;]+(?:\.[^.;]+)*?);', re.U)
# reexception = re.compile(r'7257b50d-e37a-4664-b1a5-b1340b4206c0: (.*?)$', re.U | re.M)

# JAVA_SANDBOX = os.path.abspath(os.path.join(os.path.dirname(__file__), 'java_sandbox.jar'))


# def find_class(source: str) -> str:
#     source = reinline_comment.sub('', restring.sub('', recomment.sub('', source)))
#     class_name = reclass.search(source)
#     if class_name is None:
#         raise CompileError('No public class: your main class must be declared as a "public class"\n')
#     package = repackage.search(source)
#     if package:
#         raise CompileError(f'Invalid package {package.group(1)}: do not declare package\n')
#     return class_name.group(1)


# def handle_procctl(debugger: Debugger) -> bool:
#     P_PID = 0
#     PROC_STACKGAP_CTL = 17
#     PROC_STACKGAP_STATUS = 18
#     return (
#         debugger.arg0 == P_PID
#         and debugger.arg1 == debugger.pid
#         and debugger.arg2 in (PROC_STACKGAP_CTL, PROC_STACKGAP_STATUS)
#     )


class KarelExecutor(CompiledExecutor):
    ext = "kcode"

    vm: str
    compiler: str
    # nproc = -1

    # This syscalls are needed by Node
    compiler_syscalls = [
        "capget",
        "eventfd2",
        "shutdown",
        "pkey_alloc",
        "pkey_free",
    ]
    # Node needs to access this files
    compiler_read_fs: List[FilesystemAccessRule] = [
        ExactFile("/usr/lib/ssl/openssl.cnf"),
    ]

    # This is due to the script-like compiler
    def get_compiler_read_fs(self) -> List[FilesystemAccessRule]:
        fs = self.get_fs() + self.compiler_read_fs
        compiler = self.get_compiler()
        fs += [ExactFile(compiler)]
        compiler_dir = os.path.dirname(os.path.realpath(compiler))
        nodejs_bin = Path(compiler).parent

        nodjes_lib = Path(compiler_dir).parent.parent
        # Give access to full node/bin
        fs += [RecursiveDir(nodejs_bin)]
        # Give full access to node/lib
        fs += [RecursiveDir(nodjes_lib)]

        # FIXME For some reason, Node touches all paths from /home to the js file!
        def iterate(path, fs):
            current = path
            while current != os.path.dirname(
                current
            ):  # Stop at one level before the root
                fs += [ExactDir(current)]  # Print or process the current directory
                current = os.path.dirname(current)

        iterate(compiler_dir, fs)
        return fs

    def get_compile_env(self):
        env = os.environ.copy()
        if env is None:
            env = {}
        env["UV_USE_IO_URING"] = "0"
        return env

    # fsize = 1048576  # Allow 1 MB for writing crash log.
    # address_grace = 786432

    # jvm_regex: Optional[str] = None
    # _class_name: Optional[str]

    def __init__(self, problem_id: str, source_code: bytes, **kwargs) -> None:
        super().__init__(problem_id, source_code, **kwargs)

    # def get_compile_popen_kwargs(self) -> Dict[str, Any]:
    #     return {'executable': utf8bytes(self.get_compiler())}

    # def get_compiled_file(self) -> str:
    #     return ''

    def get_executable(self) -> str:
        vm = self.get_vm()
        assert vm is not None
        return vm

    # def get_fs(self) -> List[FilesystemAccessRule]:
    #     fs = (
    #         super().get_fs()
    #         + [ExactFile(self._agent_file)]
    #         + [ExactDir(str(parent)) for parent in PurePath(self._agent_file).parents]
    #     )
    #     vm = self.get_vm()
    #     assert vm is not None
    #     vm_parent = Path(os.path.realpath(vm)).parent.parent
    #     vm_config = Path(glob.glob(f'{vm_parent}/**/jvm.cfg', recursive=True)[0])
    #     if vm_config.is_symlink():
    #         fs += [RecursiveDir(os.path.dirname(os.path.realpath(vm_config)))]
    #     return fs

    # def get_write_fs(self) -> List[FilesystemAccessRule]:
    #     assert self._dir is not None
    #     return super().get_write_fs() + [ExactFile(os.path.join(self._dir, 'submission_jvm_crash.log'))]

    # def get_agent_flag(self) -> str:
    #     hints = [*self._hints]
    #     if self.unbuffered:
    #         hints.append('nobuf')
    #     return f'-javaagent:{self._agent_file}={",".join(hints)}'

    #     return [self.problem]

    # def launch(self, *args, **kwargs) -> TracedPopen:
    #     kwargs['orig_memory'], kwargs['memory'] = kwargs['memory'], 0
    #     return super().launch(*args, **kwargs)

    def populate_result(
        self, stderr: bytes, result: Result, process: TracedPopen
    ) -> None:
        super().populate_result(stderr, result, process)
        if process.is_ir:
            if process.returncode == 20:
                result.result_flag |= Result.MLE
            elif process.returncode >= 48 and process.returncode <= 63:
                result.result_flag |= Result.TLE

    def parse_feedback_from_stderr(self, stderr: bytes, process: TracedPopen) -> str:
        exception = "Error de juez (Error desconocido)"
        if process.returncode == 2:
            exception = "Error de juez (Versión de la VM incorrecta)"
        elif process.returncode == 16:
            exception = "Error de ejecución (Karel chocó con un muro)"
        elif process.returncode == 17:
            exception = "Error de ejecución (Posición sin zumbadores)"
        elif process.returncode == 18:
            exception = "Error de ejecución (Mochila vacía sin zumbadores)"
        elif process.returncode == 19:
            exception = "Error de ejecución (Pila de llamadas desbordada)"
        elif process.returncode == 20:
            exception = "Límite de memoria (Memoria de la pila llena)"
        elif process.returncode == 21:
            exception = "Error de ejecución (Demasiados parametros)"
        elif process.returncode == 22:
            exception = "Error de ejecución (Número demasiado grande)"
        elif process.returncode == 23:
            exception = "Error de ejecución (Número demasiado pequeño)"
        elif process.returncode == 24:
            exception = "Error de ejecución (Montón demasiado grande)"
        elif process.returncode == 25:
            exception = "Error de ejecución (Mochila desbordada)"
        elif process.returncode == 48:
            exception = "Límite de instrucciones excedido (General)"
        elif process.returncode == 49:
            exception = "Límite de instrucciones excedido (Izquierdas)"
        elif process.returncode == 50:
            exception = "Límite de instrucciones excedido (Avanzas)"
        elif process.returncode == 51:
            exception = "Límite de instrucciones excedido (Coge-zumbadores)"
        elif process.returncode == 52:
            exception = "Límite de instrucciones excedido (Deja-zumbadores)"

        return exception

    @classmethod
    def get_vm(cls) -> Optional[str]:
        return cls.runtime_dict.get(cls.vm)

    @classmethod
    def get_compiler(cls) -> Optional[str]:
        return cls.runtime_dict.get(cls.compiler)

    @classmethod
    def initialize(cls) -> bool:
        vm = cls.get_vm()
        compiler = cls.get_compiler()
        if vm is None or compiler is None:
            return False
        if not os.path.isfile(vm) or not os.path.isfile(compiler):
            return False
        return skip_self_test or cls.run_self_test()

    @classmethod
    def test_jvm(cls, name: str, path: str) -> Tuple[Dict[str, Any], bool, str]:
        raise NotImplementedError()

    @classmethod
    def get_versionable_commands(cls) -> List[Tuple[str, str]]:
        compiler = cls.get_compiler()
        assert compiler is not None
        return [("karel", compiler)]

    def get_compile_args(self) -> List[str]:
        compiler = self.get_compiler()
        assert compiler is not None
        assert self._code is not None
        # TODO: Maybe it needs an output file
        return [
            compiler,
            "compile",
            os.path.realpath(self._code),
            "-o",
            self.get_compiled_file(),
        ]

    def get_cmdline(self, **kwargs):
        return [self.get_vm(), self.problem]

    # This is mostly the same as base_executor.run_self_test, but instead of checking echolalia, it tests for karel worlds
    @classmethod
    def run_self_test(
        cls, output: bool = True, error_callback: Optional[Callable[[Any], Any]] = None
    ) -> bool:
        if not cls.test_program:
            return True

        if output:
            print_ansi(
                f"Self-testing #ansi[{cls.get_executor_name()}](|underline):".ljust(39),
                end=" ",
            )
        try:
            executor = cls(cls.test_name, utf8bytes(cls.test_program))
            proc = executor.launch(
                time=cls.test_time,
                memory=cls.test_memory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            # Instead of checking for a program with Echolalia, check actual karel worlds
            test_message = b'<ejecucion version="1.1"><condiciones instruccionesMaximasAEjecutar="10000000" longitudStack="65000" memoriaStack="65000" llamadaMaxima="5"/><mundos><mundo nombre="mundo_0" ancho="100" alto="100"/></mundos><programas tipoEjecucion="CONTINUA" intruccionesCambioContexto="1" milisegundosParaPasoAutomatico="0"><programa nombre="p1" ruta="{$2$}" mundoDeEjecucion="mundo_0" xKarel="1" yKarel="1" direccionKarel="NORTE" mochilaKarel="0"/></programas></ejecucion>'
            expected_output = b"""<resultados>
	<programas>
		<programa nombre="p1" resultadoEjecucion="FIN PROGRAMA"/>
	</programas>
</resultados>
"""
            stdout, stderr = proc.communicate(test_message + b"\n")

            if proc.is_tle:
                print_ansi("#ansi[Time Limit Exceeded](red|bold)")
                return False
            if proc.is_mle:
                print_ansi("#ansi[Memory Limit Exceeded](red|bold)")
                return False

            res = stdout.strip() == expected_output.strip() and not stderr
            if output:
                # Cache the versions now, so that the handshake packet doesn't take ages to generate
                cls.get_runtime_versions()
                usage = f"[{proc.execution_time:.3f}s, {proc.max_memory} KB]"
                print_ansi(
                    f"{['#ansi[Failed](red|bold) ', '#ansi[Success](green|bold)'][res]} {usage:<19}",
                    end=" ",
                )
                print_ansi(
                    ", ".join(
                        [
                            f"#ansi[{runtime}](cyan|bold) {'.'.join(map(str, version))}"
                            for runtime, version in cls.get_runtime_versions()
                        ]
                    )
                )
            if stdout.strip() != test_message.strip() and error_callback:
                error_callback("Got unexpected stdout output:\n" + utf8text(stdout))
            if stderr:
                if error_callback:
                    error_callback("Got unexpected stderr output:\n" + utf8text(stderr))
                else:
                    print(stderr, file=sys.stderr)
            if proc.protection_fault:
                print_protection_fault(proc.protection_fault)
            return res
        except Exception:
            if output:
                print_ansi("#ansi[Failed](red|bold)")
                traceback.print_exc()
            if error_callback:
                error_callback(traceback.format_exc())
            return False

    def get_compile_popen_kwargs(self) -> Dict[str, Any]:
        return {"executable": utf8bytes(self.get_compiler())}

    def get_compile_args(self) -> List[str]:
        compiler = self.get_compiler()
        assert compiler is not None
        assert self._code is not None
        # TODO: Maybe it needs an output file
        return [compiler, "compile", self._code, "-o", self.get_compiled_file()]

    def handle_compile_error(self, output: bytes):
        if b"is public, should be declared in a file named" in utf8bytes(output):
            raise CompileError(
                "You are a troll. Trolls are not welcome. As a judge, I sentence your code to death.\n"
            )
        raise CompileError(output)

    @classmethod
    def get_find_first_mapping(cls) -> Optional[Dict[str, List[str]]]:
        return {"rekarel": ["rekarel"], "karel": ["karel"]}


if __name__ == "__main__":
    # This is just to test the executor
    KarelExecutor.initialize()
    executor = KarelExecutor(
        "test",
        """\
usa rekarel.globales;
iniciar-programa
	inicia-ejecucion
		{ TODO poner codigo aqui }
		apagate;
	termina-ejecucion
finalizar-programa""",
    )
    if executor.run_self_test():
        print("Self-test passed!")
    else:
        print("Self-test failed!")
