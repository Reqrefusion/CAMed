"""Commands exposed in CAMed menus; search is available through shortcuts."""

from .i18n import tr

ACTION_SPECS = {
    'Sections': (
        tr('Program sections'),
        'Ctrl+Alt+O',
        ':/icons/tree-doc-multi.svg',
        tr('Show or hide program sections'),
    ),
    'Renumber': (
        tr('Number lines'),
        None,
        ':/icons/Param_Int.svg',
        tr('Number the selection or program as N10, N20…'),
    ),
    'RemoveNumbers': (
        tr('Remove line numbers'),
        None,
        ':/icons/Param_Int.svg',
        tr('Remove N line numbers from the selection or program'),
    ),
}
ACTION_GROUPS = (
    (tr('Line numbers'), ('Renumber', 'RemoveNumbers')),
    (tr('View'), ('Sections',)),
)
