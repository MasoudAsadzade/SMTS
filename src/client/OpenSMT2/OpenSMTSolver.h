//
// Created by Matteo on 22/07/16.
//

#ifndef CLAUSE_SERVER_OPENSMTSOLVER_H
#define CLAUSE_SERVER_OPENSMTSOLVER_H

#include "SimpSMTSolver.h"
#include "Interpret.h"
#include "client/SolverProcess.h"
#include "client/Settings.h"


namespace opensmt {
    extern bool stop;
}


class OpenSMTInterpret : public Interpret {
    friend class OpenSMTSolver;
    friend class SolverProcess;

private:
    std::map<std::string, std::string> &header;
    Socket *clause_socket;
protected:
    void new_solver();

public:
    OpenSMTInterpret(std::map<std::string, std::string> &header, Socket *clause_socket, SMTConfig &c) :
            Interpret(c),
            header(header),
            clause_socket(clause_socket) { }

};

class OpenSMTSolver : public SimpSMTSolver {
private:
    OpenSMTInterpret &interpret;
    uint32_t trail_sent;

    void inline clausesPublish();

    void inline clausesUpdate();

public:
    OpenSMTSolver(OpenSMTInterpret &interpret);

    ~OpenSMTSolver();
};


#endif //CLAUSE_SERVER_OPENSMTSOLVER_H
