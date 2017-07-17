let exec = require('child_process').execSync;
let config = require('./config.js');

let path = config.path;     // Path to the server python file
let port = config.port;     // Server port
let python = config.python; // Python command-line

function run(command) {
    if (!port) {
        console.log('Error: no port');
        process.exit();
    } else if (!path) {
        console.log('Error: no path');
        process.exit();
    }
    return exec(`${command} | ${python} ${path} ${port}`, {'encoding': 'utf8'}).trim();
}

module.exports = {

    setPath: function (_path) {
        path = _path;
    },

    setPort: function (_port) {
        port = _port;
    },

    getDatabase: function () {
        return run("echo 'self.config.db().execute(\"PRAGMA database_list\").fetchall()[0][2] if self.config.db() else \"Empty\"'");
    },

    getInstance: function () {
        return run("echo 'self.current.root.name if self.current else \"Empty\"'");
    },

    getRemainingTime: function () {
        return run("echo 'self.current.when_timeout if self.current else \"Empty\"'");
    },

    getCurrent: function () {
        return [this.getInstance(), this.getRemainingTime()];
    },

    increaseTimeout: function (timeout) {
        return run(`echo 'exec('self.current.timeout+='${timeout}')' if self.current != 'None' else \"Nothing to reset\"'`);

    },

    decreaseTimeout: function (timeout) {
        return run(`echo 'exec('self.current.timeout-='${timeout}')' if self.current != 'None' else \"Nothing to reset\"'`);
    },

    stopSolving: function () {
        return run("echo 'exec('self.current.timeout=1')' if self.current != 'None' else \"Nothing to reset\"'");
    }

};
