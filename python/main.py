import os
from six.moves import configparser

from flask import Flask
from captive_portal.manager import setup_captive_portal_app, show_captive_portal_welcome
from chat.server import register as register_chat

config_parser = configparser.ConfigParser()
config_parser.readfp(open('%s/defaults.cfg' % os.path.dirname(os.path.abspath(__file__))))
config_parser.read(['/usr/local/connectbox/etc/connectbox.conf'])

DATABASE_DIRECTORY = config_parser.get('main', 'DATABASE_DIRECTORY')

def chat_connection_info():
    """ get db connection info string """
    return 'sqlite:///%s/cbchat.db' % (DATABASE_DIRECTORY)

app = Flask(__name__)

setup_captive_portal_app(app)
register_chat(app, chat_connection_info)

# There's no simple way to set an error handler without using a decorator
#  but that requires app to be defined at the top level, and before use of
#  the decorator.
@app.errorhandler(404)
def default_view(_):
    """Handle all URLs and send them to the captive portal welcome page"""
    return show_captive_portal_welcome()

# @app.route('/foo')
# def foo():
#     return jsonify({'tasks': ['a','b','c']})

if __name__ == "__main__":
    # XXX debug should be off for non-development releases
    app.run(host='::', port=5000, debug=True)
