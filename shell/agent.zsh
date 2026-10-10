# A line ending in "??" or "??MODEL" is sent to agent-run as a question instead of to zsh.
# This shadows a command line whose last word ends in a ?? glob.
# Ctrl-X Ctrl-A replaces the prompt's text with a command suggested by agent-suggest-command.

agent-question-command() {
    [[ $1 =~ '^(.+)\?\?([[:alnum:]_.-]*)[[:space:]]*$' ]] || return 0
    print -r -- "agent-run${match[2]:+ -m $match[2]} <<< ${(qq)match[1]}"
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
