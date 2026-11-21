"""Legacy thread imports and shared worker catches use one exception identity."""
from extensions.commands.tickets import thread_service
from utils import manage_web_worker
from utils.ticket_errors import ThreadConfigurationError, ThreadTicketError


def test_shared_ticket_exception_identity_and_base_chain():
    assert thread_service.ThreadTicketError is ThreadTicketError
    assert thread_service.ThreadConfigurationError is ThreadConfigurationError
    assert manage_web_worker.ThreadConfigurationError is ThreadConfigurationError
    assert ThreadTicketError.__bases__ == (RuntimeError,)
    assert ThreadConfigurationError.__bases__ == (ThreadTicketError,)
    assert thread_service.ThreadCreationBusy.__bases__ == (ThreadTicketError,)
    assert isinstance(thread_service.ThreadConfigurationError("same reason"), RuntimeError)
    assert str(ThreadConfigurationError("same reason")) == "same reason"
