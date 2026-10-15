import sys

USAGE = """Uso: catprinter [ARCHIVOS…]
     catprinter --instalar     Integra la app con el escritorio y Archivos
     catprinter --desinstalar  Quita la integración"""


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "--ayuda"):
        print(USAGE)
        return 0
    if args and args[0] in ("--instalar", "--install", "--desinstalar", "--uninstall"):
        from catprinter_gui import integration
        try:
            if args[0] in ("--instalar", "--install"):
                print(integration.install())
            else:
                print(integration.uninstall())
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 1
        return 0

    from catprinter_gui.application import Application
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
