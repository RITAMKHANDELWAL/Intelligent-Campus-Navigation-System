
"""
main.py – entry point of the Intelligent Campus Navigation System.

    python main.py
"""
import sys

def main():
    try:
        from ui import CampusNavigationApp
    except ModuleNotFoundError as exc:
        print(f"Missing dependency: {exc.name}\n"
              f"Install the requirements first:\n    pip install -r requirements.txt")
        sys.exit(1)
    from enhancements import install_enhancements  # [enh-hook] add-on layer (prompt 2)
    install_enhancements()                          # [enh-hook] must run before the app is created
    app = CampusNavigationApp()
    app.mainloop()

if __name__ == "__main__":
    main()
