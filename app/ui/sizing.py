"""
Making a stepped dialog only as tall as the step it is showing.

``QStackedWidget`` reports the size of its *largest* page, not the visible one,
because every page has to be able to appear without the window jumping. For a
wizard that is exactly wrong: the sign-up form is six fields tall, so the
one-field "enter the code" step inherits its height and shows a few hundred
pixels of nothing, with the buttons pushed toward the bottom of the screen.

The fix is to tell the layout to ignore the pages that are not on screen.
A widget with :attr:`QSizePolicy.Policy.Ignored` contributes nothing to its
parent's size hint, so the stack ends up the height of the current page alone.

    fit_stack_to_current_page(self.pages, self)

Call it on every step change, after switching pages. The window does then
change height between steps, which is the point — it follows the content
instead of being permanently sized for the worst case.

Passing the window matters. Changing a policy only marks the layouts dirty;
Qt recalculates them when it next gets round to it, which is *after* the
current function returns. A plain ``adjustSize()`` on the next line therefore
measures the old hint and the window keeps the height it already had. The
layouts between the stack and the window have to be invalidated and activated
first, which is what :func:`fit_stack_to_current_page` does before resizing.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QWidget


def fit_stack_to_current_page(stack: QStackedWidget, window: QWidget | None = None) -> None:
    """Shrink ``stack`` — and optionally the window holding it — to the visible page.

    ``window`` is the dialog to resize afterwards. Leave it out to change only
    the stack, for a caller that will settle the geometry itself.
    """
    current = stack.currentIndex()

    for index in range(stack.count()):
        page = stack.widget(index)

        if page is None:
            continue

        policy = page.sizePolicy()
        policy.setVerticalPolicy(
            QSizePolicy.Policy.Preferred
            if index == current
            else QSizePolicy.Policy.Ignored
        )
        page.setSizePolicy(policy)

    stack.updateGeometry()
    stack.adjustSize()

    if window is None:
        return

    # Walk up from the stack recalculating every layout in between, innermost
    # first. Invalidating alone is not enough: it only marks them dirty, and Qt
    # rebuilds them on a later event-loop turn, so the window's *minimum* would
    # still be the previous step's height when it is measured a line later.
    # QWidget.adjustSize() clamps to that minimum, and the window would keep
    # the taller size until something else triggered a second pass.
    widget = stack

    while widget is not None:
        layout = widget.layout()

        if layout is not None:
            layout.invalidate()
            layout.activate()

        if widget is window:
            break

        widget = widget.parentWidget()

    # Now that the page has a real width, pin every wrapped label to the height
    # its text needs, and settle the layouts once more so the window is
    # measured with those heights. Without this the window is sized from the
    # layout's guess at how tall the wrapped text will be, which is short, and
    # the last line of a message gets cut off.
    for label in stack.currentWidget().findChildren(QLabel):
        if label.wordWrap():
            fit_wrapped_label(label)

    layout = window.layout()

    if layout is not None:
        layout.invalidate()
        layout.activate()

    window.adjustSize()
    keep_on_screen(window)


def fit_wrapped_label(label: QLabel) -> None:
    """Give a word-wrapped label the height its text actually occupies.

    ``QLabel.heightForWidth`` is used rather than measuring the string with
    font metrics, because these labels carry small amounts of rich text — bold
    names, a line break — and font metrics would measure the markup instead of
    the rendered result.
    """
    width = label.width()

    if width <= 1:
        return

    needed = label.heightForWidth(width)

    if needed > 0:
        label.setMinimumHeight(needed)


def keep_on_screen(window: QWidget) -> None:
    """Nudge ``window`` back inside the screen it is on, if it has spilled off.

    A step that grows — going back from the short "enter the code" page to the
    tall sign-up form — keeps its top-left corner, so the extra height all
    appears at the bottom and can run past the edge of the display, taking the
    buttons with it. Moving rather than resizing means a dialog the user has
    dragged somewhere deliberate stays roughly where they put it.
    """
    screen = window.screen() or QGuiApplication.primaryScreen()

    if screen is None:
        return

    area = screen.availableGeometry()
    frame = window.frameGeometry()

    # Nothing sensible to do if the window is genuinely taller than the screen;
    # pinning the top at least keeps the header and the first fields reachable.
    x = min(max(frame.x(), area.x()), max(area.x(), area.right() - frame.width() + 1))
    y = min(max(frame.y(), area.y()), max(area.y(), area.bottom() - frame.height() + 1))

    if (x, y) != (frame.x(), frame.y()):
        window.move(x, y)


def let_label_wrap(label: QLabel) -> QLabel:
    """Make a word-wrapped label measure itself by its *wrapped* height.

    ``QLabel`` leaves ``heightForWidth`` off its size policy, so a layout sizes
    it with a heuristic rather than asking how tall the text is once wrapped.
    The label then gets too little vertical room and the last line or two are
    simply cut off. Opting in makes the layout ask the real question.

    Returns the label, so it can be wrapped around a constructor call.
    """
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label
