import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from version import APP_VERSION

RELEASE_ROOT = 'https://github.com/AntonVanke/CodexDesk/releases'
RELEASE_MANIFEST = RELEASE_ROOT+'/latest/download/update.json'


class ReleaseCheck(QObject):
    checking = Signal()
    found = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.stopped = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)

    def start(self):
        self.timer.start(6*60*60*1000)
        QTimer.singleShot(3000,self.check)

    def check(self):
        if self.stopped or self.reply is not None:
            return
        self.checking.emit()
        self.get_json(RELEASE_MANIFEST,self.manifest_received)

    def get_json(self, url, received):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b'User-Agent',('CodexDesk/'+APP_VERSION).encode())
        request.setTransferTimeout(15000)
        reply = self.network.get(request)
        self.reply = reply

        def finished():
            self.reply = None
            try:
                if self.stopped:
                    return
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    raise RuntimeError(reply.errorString())
                received(json.loads(bytes(reply.readAll())))
            except (RuntimeError,ValueError,KeyError) as error:
                self.failed.emit(str(error))
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def manifest_received(self, manifest):
        tag='v'+manifest['app']['version']
        self.found.emit({'url':RELEASE_ROOT+'/tag/'+tag,'tag':tag,
            **{kind:{'version':manifest[kind]['version'],'url':RELEASE_ROOT+'/download/'+tag+'/'+manifest[kind]['asset']}
               for kind in ('app','firmware')}})

    def stop(self):
        self.stopped = True
        self.timer.stop()
        if self.reply is not None:
            self.reply.abort()
