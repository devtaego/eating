from fridge_protein.simple_ui import build_app, CSS
if __name__=='__main__':
    build_app().launch(server_name='127.0.0.1',share=False,inbrowser=False,css=CSS)
