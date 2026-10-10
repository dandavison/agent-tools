# "? question" or "?MODEL question" at the prompt is sent to agent-run instead of to zsh.
# Ctrl-X Ctrl-A replaces the prompt's text with a command suggested by agent-suggest-command.

agent-question-command() {
    [[ $1 =~ '^\?([[:alnum:]_.-]*) (.+)$' ]] || return 0
    print -r -- "agent-run${match[1]:+ -m $match[1]} <<< ${(qq)match[2]}"
}

agent-accept-line() {
    local cmd=$(agent-question-command $BUFFER)
    [[ -n $cmd ]] && BUFFER=$cmd
    zle accept-line
}

agent-suggest-command-widget() {
    [[ -n $BUFFER ]] || return
    zle -I
    local cmd
    cmd=$(print -r -- $BUFFER | agent-suggest-command) || return
    BUFFER=$cmd
    CURSOR=$#BUFFER
}

zle -N agent-accept-line
zle -N agent-suggest-command-widget
bindkey '^M' agent-accept-line
bindkey '^x^a' agent-suggest-command-widget
