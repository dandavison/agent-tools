# Text ending in "|" or "| MODEL" (a model name in agent-models.toml) is sent to agent-run
# instead of to zsh. A trailing "|" is incomplete shell syntax, but "| MODEL" shadows a real
# pipeline into a command with that name.
# Ctrl-X Ctrl-A replaces the prompt's text with a command suggested by agent-suggest-command.

agent-text-command() {
    [[ $1 =~ '^(.*[^|[:space:]])[[:space:]]*\|[[:space:]]*([[:alnum:]_.-]*)[[:space:]]*$' ]] || return 0
    local text=$match[1] model=$match[2]
    [[ -z $model ]] || (( ${${(f)"$(agent-model-names)"}[(Ie)$model]} )) || return 0
    print -r -- "agent-run${model:+ -m $model} <<< ${(qq)text}"
}

agent-model-names() {
    local line
    for line in "${(@f)$(<${AGENT_MODELS:-~/.config/agent-models.toml})}"; do
        [[ $line =~ '^name = "(.*)"$' ]] && print -r -- $match[1]
    done
}

agent-accept-line() {
    local cmd=$(agent-text-command "$BUFFER")
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
